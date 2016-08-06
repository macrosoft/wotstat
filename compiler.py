import py_compile, zipfile, os

WOTVersion = "0.9.15.1"
language = 'ru' # 'ru' or 'en'

if os.path.exists("wotstat.zip"):
    os.remove("wotstat.zip")

py_compile.compile("src/__init__.py")
py_compile.compile("src/CameraNode.py")
py_compile.compile("src/stat.py")

fZip = zipfile.ZipFile("wotstat.zip", "w")
fZip.write("src/__init__.pyc", WOTVersion+"/scripts/client/mods/__init__.pyc")
fZip.write("src/stat.pyc", WOTVersion+"/scripts/client/mods/stat.pyc")
fZip.write("src/CameraNode.pyc", WOTVersion+"/scripts/client/CameraNode.pyc")
fZip.write("data/config_"+language+".json", WOTVersion+"/scripts/client/mods/wotstat/config.json")
fZip.write("data/expected_tank_values.json", WOTVersion+"/scripts/client/mods/wotstat/expected_tank_values.json")
fZip.write("data/bgIcon#FFFFFF.png", WOTVersion+"/scripts/client/mods/wotstat/img/bgIcon#FFFFFF.png")
fZip.write("data/bgIcon#FE0E00.png", WOTVersion+"/scripts/client/mods/wotstat/img/bgIcon#FE0E00.png")
fZip.write("data/bgIcon#FE7903.png", WOTVersion+"/scripts/client/mods/wotstat/img/bgIcon#FE7903.png")
fZip.write("data/bgIcon#F8F400.png", WOTVersion+"/scripts/client/mods/wotstat/img/bgIcon#F8F400.png")
fZip.write("data/bgIcon#60FF00.png", WOTVersion+"/scripts/client/mods/wotstat/img/bgIcon#60FF00.png")
fZip.write("data/bgIcon#02C9B3.png", WOTVersion+"/scripts/client/mods/wotstat/img/bgIcon#02C9B3.png")
fZip.write("data/bgIcon#D042F3.png", WOTVersion+"/scripts/client/mods/wotstat/img/bgIcon#D042F3.png")

fZip.close()
