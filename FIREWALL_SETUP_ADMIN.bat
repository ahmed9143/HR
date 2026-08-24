@echo off
netsh advfirewall firewall delete rule name="HR Enterprise 7.5" >nul 2>&1
netsh advfirewall firewall add rule name="HR Enterprise 7.5" dir=in action=allow protocol=TCP localport=8899-8920 profile=private
netsh advfirewall firewall add rule name="HR Enterprise Discovery 7.5" dir=in action=allow protocol=UDP localport=8898 profile=private
echo Firewall rules created for Private networks.
pause
