@echo off
REM ============================================================
REM  PAK 재바인딩 테스트 실행 (pak_rebind_test.py)
REM  - PAK MCP 와 동일한 python / 환경으로 구동
REM  - PAK 을 켜 두고(그리고 row1 에 aaa.atfx 가 걸린 상태) 실행하세요.
REM  - 실행 중 다른 PAK 자동화(Claude 포함)는 멈춰 두세요 (COM 단일 연결).
REM ============================================================

REM 한글 출력을 위해 UTF-8 코드페이지
chcp 65001 >nul

REM MCP 설정과 동일한 환경변수
set "PAK_PROGID=Pak.Application.1"
set "PAK_TCL_INIT=C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl"

REM 스크립트 폴더로 이동
cd /d "C:\MCPProject_pak"

echo.
echo === PAK 재바인딩 테스트 시작 ===
echo.

python "C:\MCPProject_pak\pak_rebind_test.py"

echo.
echo === 테스트 종료 ===
pause
