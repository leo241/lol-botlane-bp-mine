# -*- mode: python ; coding: utf-8 -*-


block_cipher = None


# 强制收集 psutil 的全部内容（纯模块 + 原生扩展 _psutil_windows.pyd）。
# 只用 hiddenimports 时，onefile/onedir 冻结后原生扩展没被打进包，
# 导致 import psutil 失败 → LCU 在国服 WeGame 下无法识别客户端。
from PyInstaller.utils.hooks import collect_all
_ps_datas, _ps_bins, _ps_hidden = collect_all('psutil')

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=_ps_bins,
    datas=[
        ('data', 'data'),
        ('templates', 'templates'),
        ('static', 'static'),
        ('scraper/chinese_getchampion/英雄名字.txt', 'scraper/chinese_getchampion'),
        ('icon.png', '.'),
    ] + _ps_datas,
    hiddenimports=[
        'pypinyin',
        'pystray',
        'pystray._win32',
        'PIL',
        'PIL.Image',
        'psutil',
        'requests',
        'scrapling',
        'scrapling.fetchers',
        'update_data',
        'pre_fetch',
        'test_api',
        'scraper',
        'scraper.lolalytics',
        'scraper.lolalytics_timeline',
        'scraper.champion_map',
        'scraper.riot',
        'scraper.chinese_getchampion.znchampion',
        'scraper.chinese_getchampion.hero_id_mapping',
    ] + _ps_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='LolBp',
    icon='icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
