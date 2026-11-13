@echo off
rem Read-only window onto the little house. Close the window to exit.
cd /d "%~dp0house"
python -m littlehouse --view %*
