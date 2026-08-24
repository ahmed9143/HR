import os, sys, threading, time, webbrowser, urllib.request
from pathlib import Path
try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    pystray=None
BASE=Path(__file__).resolve().parent

def icon_image():
    im=Image.new('RGBA',(64,64),'white'); d=ImageDraw.Draw(im); d.rounded_rectangle((4,4,60,60),10,fill=(23,92,211,255)); d.text((18,18),'HR',fill='white'); return im

def run():
    if not pystray: return
    def open_hr(icon,item): webbrowser.open(os.environ.get('HR_CLIENT_URL','http://127.0.0.1:8899'))
    def status(icon,item): webbrowser.open(os.environ.get('HR_CLIENT_URL','http://127.0.0.1:8899')+'/system')
    def network(icon,item): webbrowser.open(os.environ.get('HR_CLIENT_URL','http://127.0.0.1:8899')+'/network')
    def backup(icon,item): webbrowser.open(os.environ.get('HR_CLIENT_URL','http://127.0.0.1:8899')+'/backups')
    menu=pystray.Menu(pystray.MenuItem('Open HR',open_hr),pystray.MenuItem('Server Status',status),pystray.MenuItem('Network',network),pystray.MenuItem('Backup',backup),pystray.MenuItem('Exit',lambda i,x:i.stop()))
    pystray.Icon('HR Enterprise',icon_image(),'HR Enterprise',menu).run()
if __name__=='__main__': run()
