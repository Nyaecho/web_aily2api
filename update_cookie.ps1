<#
.SYNOPSIS
    通过 playwright-cli 自动登录飞书，提取 Cookie 写入配置文件。

.DESCRIPTION
    使用 playwright-cli 启动有头浏览器，等待用户扫码登录后提取 Cookie。
    配合 aily_server.py 使用，Cookie 过期时运行此脚本更新。
    Cookie 提取通过 CDP Network.getAllCookies 获取（含 httpOnly）。

.PARAMETER Output
    输出配置文件路径（默认: config.json）

.PARAMETER Timeout
    登录超时秒数（默认: 300）

.PARAMETER Profile
    持久化浏览器配置目录（可选，用于保存登录状态）

.PARAMETER Browser
    浏览器类型（默认: msedge）

.PARAMETER Validate
    仅验证现有配置文件中的 Cookie

.EXAMPLE
    .\update_cookie.ps1
    .\update_cookie.ps1 -Output my.json -Timeout 600
    .\update_cookie.ps1 -Browser msedge -Profile "$env:USERPROFILE\.feishu-profile"
    .\update_cookie.ps1 -Validate
#>

param(
    [string]$Output = "config.json",
    [int]$Timeout = 300,
    [string]$Profile = "",
    [ValidateSet("chromium", "chrome", "msedge", "firefox", "webkit")]
    [string]$Browser = "msedge",
    [switch]$Validate
)

$ErrorActionPreference = "Stop"

# ==================== 常量 ====================

$BaseUrl = "https://aily.feishu.cn"
$LoginUrl = "https://login.feishu.cn/accounts/page/login?app_id=149&query_scope=all&redirect_uri=https%3A%2F%2Faily.feishu.cn"

# ==================== 辅助函数 ====================

function Test-Cookie {
    param([string]$CookieStr)
    $required = @("session", "swp_csrf_token")
    foreach ($name in $required) {
        if ($CookieStr -notmatch [regex]::Escape($name)) {
            return $false
        }
    }
    return $true
}

# ==================== 验证模式 ====================

if ($Validate) {
    if (-not (Test-Path $Output)) {
        Write-Host "[!] 配置文件不存在: $Output" -ForegroundColor Red
        exit 1
    }
    $data = Get-Content $Output -Raw | ConvertFrom-Json
    $cookie = $data.cookie
    if (Test-Cookie $cookie) {
        $age = [int][double]::Parse((Get-Date -UFormat %s)) - $data.updated_at
        $hours = [math]::Floor($age / 3600)
        $mins = [math]::Floor(($age % 3600) / 60)
        Write-Host "[+] Cookie 有效 (更新于 ${hours}h ${mins}m 前)" -ForegroundColor Green
    } else {
        Write-Host "[!] Cookie 无效或缺失关键字段" -ForegroundColor Red
        exit 1
    }
    exit 0
}

# ==================== 环境检查 ====================

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    Write-Host "[!] 未找到 npx，请先安装 Node.js" -ForegroundColor Red
    exit 1
}

# 检查 playwright-cli 是否可用
try {
    $version = & npx --no-install playwright-cli --version 2>&1
    Write-Host "[*] playwright-cli 版本: $version" -ForegroundColor Gray
} catch {
    Write-Host "[*] 安装 playwright-cli..." -ForegroundColor Yellow
    npm install -g @playwright/cli@latest
}

# ==================== 启动浏览器（有头模式）====================

Write-Host "[*] 启动 Cookie 更新流程 → $Output" -ForegroundColor Cyan

$openArgs = @("open", "--browser=$Browser", "--headed")
if ($Profile) {
    $openArgs += "--persistent"
    $openArgs += "--profile=$Profile"
}
$openArgs += $BaseUrl

Write-Host "[*] 启动浏览器 ($Browser, 有头模式)..." -ForegroundColor Yellow
& npx playwright-cli @openArgs

# 检查当前 URL，判断是否已登录
$currentUrl = & npx playwright-cli --raw eval "window.location.href"
if ($currentUrl -match "aily\.feishu\.cn" -and $currentUrl -notmatch "accounts\.feishu\.cn" -and $currentUrl -notmatch "landing") {
    Write-Host "[+] 已登录，直接提取 Cookie" -ForegroundColor Green
} else {
    Write-Host "[*] 跳转到登录页..." -ForegroundColor Yellow
    & npx playwright-cli goto $LoginUrl
    Write-Host ("=" * 60) -ForegroundColor Cyan
    Write-Host "请在浏览器窗口中扫码或完成登录（超时: ${Timeout}s）" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor Cyan

    $startTime = Get-Date
    $loggedIn = $false
    while (-not $loggedIn) {
        $elapsed = ((Get-Date) - $startTime).TotalSeconds
        if ($elapsed -gt $Timeout) {
            Write-Host "[!] 登录超时（${Timeout}s）" -ForegroundColor Red
            & npx playwright-cli close
            exit 1
        }

        Start-Sleep -Seconds 3
        $currentUrl = & npx playwright-cli --raw eval "window.location.href"
        if ($currentUrl -match "aily\.feishu\.cn" -and $currentUrl -notmatch "accounts\.feishu\.cn" -and $currentUrl -notmatch "landing") {
            $loggedIn = $true
            Write-Host "[+] 登录成功: $currentUrl" -ForegroundColor Green
        }
    }
}

# ==================== 提取 Cookie（CDP Network.getAllCookies）====================
# session / swp_csrf_token 是 httpOnly，document.cookie 拿不到
# 用 CDP 协议直接从浏览器层面获取全部 cookie

Write-Host "[*] 等待页面稳定..." -ForegroundColor Yellow
Start-Sleep -Seconds 1

Write-Host "[*] 通过 CDP 提取 Cookie..." -ForegroundColor Yellow

$cdpJs = @"
async page => {
    const ctx = page.context();
    const client = await ctx.newCDPSession(page);
    const result = await client.send('Network.getAllCookies');
    const filtered = result.cookies.filter(c =>
        c.domain && (c.domain.includes('feishu.cn') || c.domain.includes('aily'))
    );
    return { ok: true, cookies: filtered };
}
"@
$cdpJs | Set-Content "$env:TEMP\extract-cookies-cdp.js" -Encoding UTF8

$cdpOutput = & npx playwright-cli --json run-code --filename="$env:TEMP\extract-cookies-cdp.js" 2>&1
$cdpStr = ($cdpOutput | Out-String)

# 解析：run-code --json 返回 { "result": "<stringified JSON>" }，需二次解析
$cookies = $null
try {
    $parsed = $cdpStr | ConvertFrom-Json
    $rawResult = $null
    if ($parsed.result) { $rawResult = $parsed.result }
    elseif ($parsed.value) { $rawResult = $parsed.value }
    elseif ($parsed.data) { $rawResult = $parsed.data }
    else { $rawResult = $parsed }

    if ($rawResult -is [string]) {
        $cdpResult = $rawResult | ConvertFrom-Json
    } else {
        $cdpResult = $rawResult
    }

    if ($cdpResult.ok -eq $true -and $cdpResult.cookies) {
        $cookies = $cdpResult.cookies
    }
} catch {
    $jsonMatch = [regex]::Match($cdpStr, '\{[\s\S]*\}')
    if ($jsonMatch.Success) {
        try {
            $fallback = $jsonMatch.Value | ConvertFrom-Json
            if ($fallback.ok -eq $true -and $fallback.cookies) {
                $cookies = $fallback.cookies
            }
        } catch {}
    }
}

if (-not $cookies -or $cookies.Count -eq 0) {
    Write-Host "[!] CDP Cookie 提取失败" -ForegroundColor Red
    Write-Host "    原始输出（前 500 字符）:" -ForegroundColor Yellow
    Write-Host $cdpStr.Substring(0, [math]::Min(500, $cdpStr.Length)) -ForegroundColor Yellow
    & npx playwright-cli close
    exit 1
}

Write-Host "[+] CDP 获取成功，$($cookies.Count) 个 Cookie" -ForegroundColor Green

# 构建 cookie 字符串
$cookieParts = @()
foreach ($c in $cookies) {
    if ($c.name -and $c.value) {
        $cookieParts += "$($c.name)=$($c.value)"
    }
}
$cookieStr = $cookieParts -join "; "
$cookieNames = $cookies | ForEach-Object { $_.name }

# 提取 device_id
$deviceId = "75832975860815"

# 验证关键字段
if (-not (Test-Cookie $cookieStr)) {
    $missing = @("session", "swp_csrf_token") | Where-Object { $cookieNames -notcontains $_ }
    Write-Host "[!] Cookie 验证失败：缺少关键字段 $missing" -ForegroundColor Red
    Write-Host "    获取到 $($cookies.Count) 个 Cookie: $($cookieNames -join ', ')" -ForegroundColor Yellow
    Write-Host "    提示: 登录可能未完全完成，请重新运行" -ForegroundColor Yellow
    & npx playwright-cli close
    exit 1
}

# 关闭浏览器
& npx playwright-cli close

# ==================== 写入配置 ====================

$updatedAt = [int][double]::Parse((Get-Date -UFormat %s))

# 读取现有配置（保留端口等设置）
$existing = @{}
if (Test-Path $Output) {
    $existing = Get-Content $Output -Raw | ConvertFrom-Json -AsHashtable
}

$config = @{
    cookie       = $cookieStr
    device_id    = $deviceId
    port         = if ($existing.port) { $existing.port } else { 8765 }
    host         = if ($existing.host) { $existing.host } else { "0.0.0.0" }
    workspace_id = if ($existing.workspace_id) { $existing.workspace_id } else { "7664492972083334362" }
    updated_at   = $updatedAt
}

$config | ConvertTo-Json -Depth 10 | Set-Content $Output -Encoding UTF8

$updateTime = [DateTimeOffset]::FromUnixTimeSeconds($updatedAt).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss")
Write-Host "[+] Cookie 已写入: $Output" -ForegroundColor Green
Write-Host "    $($cookies.Count) 个 Cookie, $($cookieStr.Length) 字节" -ForegroundColor Gray
Write-Host "    更新时间: $updateTime" -ForegroundColor Gray
Write-Host "    现在可以启动服务: python3 aily_server.py --config $Output" -ForegroundColor Cyan
