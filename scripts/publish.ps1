<#
.SYNOPSIS
    将 ai-gesture-game 推送到 Gitee / GitHub。

.DESCRIPTION
    推送前会：检查 Git 仓库 → 在缺失时写入本仓库提交身份 → 提交未提交改动
    → 配置远端 → push → 用 git ls-remote 核验远端分支。
    远端仓库必须先在网页上创建为空仓库（不要勾选初始化 README）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/publish.ps1 -Remote gitee

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/publish.ps1 -Remote all -GitHubUser yourname
#>
param(
    [ValidateSet("gitee", "github", "all")]
    [string]$Remote = "gitee",

    [string]$RepoName = "ai-gesture-game",
    [string]$GiteeUser = "rainprayer",
    [string]$GitHubUser = "",
    [string]$Branch = "main",
    [string]$Message = "chore: first public release",
    [switch]$SkipCommit
)

$ErrorActionPreference = "Stop"

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    exit 1
}

function Info([string]$msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Ok([string]$msg)   { Write-Host "[ OK ] $msg" -ForegroundColor Green }

# 1. 定位仓库根目录（本脚本位于 <repo>/scripts/）
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

if (-not (Test-Path (Join-Path $root ".git"))) {
    Fail "当前目录不是 Git 仓库：$root（请先执行 git init -b $Branch）"
}
if (-not (Test-Path (Join-Path $root "README.md"))) {
    Fail "仓库根目录缺少 README.md，可能不是项目根目录：$root"
}
Info "仓库目录：$root"

# 2. 提交身份（仅在本仓库缺失时写入，避免改动全局配置）
$name = (git config user.name) 2>$null
$email = (git config user.email) 2>$null
if (-not $name) {
    git config user.name "Yecheng Hong"
    Info "已写入本仓库 user.name = Yecheng Hong"
}
if (-not $email) {
    git config user.email "$GiteeUser@users.noreply.gitee.com"
    Info "已写入本仓库 user.email = $GiteeUser@users.noreply.gitee.com"
}

# 3. 提交未提交改动
if (-not $SkipCommit) {
    git add -A
    $pending = (git status --porcelain) 2>$null
    if ($pending) {
        git commit -m $Message | Out-Host
        if ($LASTEXITCODE -ne 0) { Fail "git commit 失败（检查提交身份与暂存内容）" }
        Ok "已提交本地改动"
    }
    else {
        Info "没有待提交的改动"
    }
}

$commitCount = (git rev-list --count HEAD) 2>$null
if (-not $commitCount -or [int]$commitCount -lt 1) {
    Fail "本地没有任何提交，无法推送"
}

# 4. 远端配置
$targets = @()
if ($Remote -in @("gitee", "all")) {
    $targets += [pscustomobject]@{
        Name = "gitee"
        Url  = "https://gitee.com/$GiteeUser/$RepoName.git"
    }
}
if ($Remote -in @("github", "all")) {
    if (-not $GitHubUser) {
        Fail "推送 GitHub 需要 -GitHubUser <你的GitHub用户名>"
    }
    $targets += [pscustomobject]@{
        Name = "github"
        Url  = "https://github.com/$GitHubUser/$RepoName.git"
    }
}

# 5. 逐个推送并核验
$failed = @()
foreach ($t in $targets) {
    Write-Host ""
    Info "===== $($t.Name): $($t.Url) ====="

    $existing = (git remote) 2>$null
    if ($existing -contains $t.Name) {
        git remote set-url $t.Name $t.Url
    }
    else {
        git remote add $t.Name $t.Url
    }

    # 先探测远端是否存在（空仓库也会返回成功；不存在会报错）
    git ls-remote --heads $t.Name 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] 无法访问远端仓库 $($t.Url)" -ForegroundColor Yellow
        Write-Host "       请确认：① 仓库已在网页上创建为【空仓库】；② 账号/私人令牌正确；③ 网络可达。" -ForegroundColor Yellow
        $failed += $t.Name
        continue
    }

    git push -u $t.Name $Branch
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[WARN] push 失败：$($t.Name)" -ForegroundColor Yellow
        $failed += $t.Name
        continue
    }

    $remoteHeads = (git ls-remote --heads $t.Name "refs/heads/$Branch") 2>$null
    if (-not $remoteHeads) {
        Write-Host "[WARN] push 返回成功，但远端没有 $Branch 分支（可能被拒绝）" -ForegroundColor Yellow
        $failed += $t.Name
        continue
    }
    Ok "$($t.Name) 已推送：$($t.Url)（分支 $Branch）"
}

Write-Host ""
if ($failed.Count -gt 0) {
    Write-Host "推送未全部成功：$($failed -join ', ')" -ForegroundColor Red
    Write-Host "参考 docs/PUBLISH.md 排查。" -ForegroundColor Red
    exit 1
}
Ok "全部完成。浏览器打开仓库地址确认 README 与图片渲染正常。"
