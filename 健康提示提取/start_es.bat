@echo off
chcp 65001 >nul 2>&1
setlocal

:: 可按需修改 ES 安装目录
set "ES_DIR=E:\elasticsearch-8.10.0"
set "ES_BAT=%ES_DIR%\bin\elasticsearch.bat"

echo ==============================================
echo           Start Elasticsearch For Py
echo ==============================================
echo.

if not exist "%ES_BAT%" (
    echo [ERROR] Elasticsearch 启动脚本不存在: "%ES_BAT%"
    echo 请修改 start_es.bat 中的 ES_DIR 为你的实际安装路径。
    exit /b 1
)

:: 检查 9200 端口是否已监听
netstat -ano | findstr ":9200" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo [OK] 检测到 9200 端口已监听，Elasticsearch 可能已经启动。
    goto :wait_ready
)

echo [INFO] 正在启动 Elasticsearch...
start "Elasticsearch Server" /d "%ES_DIR%" "%ES_BAT%"
echo [INFO] 已发送启动命令，等待服务就绪...

:wait_ready
set /a RETRY=0
set /a MAX_RETRY=40

:loop
set /a RETRY+=1
curl -k -s https://localhost:9200 >nul 2>nul
if %errorlevel%==0 (
    echo [OK] Elasticsearch 已可访问: https://localhost:9200
    echo [TIP] 如需验证鉴权，可执行: curl -k -u elastic:你的密码 jVaWERJ2oLooSJbdje1M
    exit /b 0
)

if %RETRY% GEQ %MAX_RETRY% (
    echo [WARN] 等待超时，请查看 Elasticsearch 窗口日志。
    exit /b 1
)

timeout /t 2 /nobreak >nul
goto :loop
