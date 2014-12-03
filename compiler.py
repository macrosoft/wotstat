import py_compile, zipfile, os

WOTVersion = "0.9.4"

if os.path.exists("wotstat.zip"):
    os.remove("wotstat.zip")

py_compile.compile("src/__init__.py")
py_compile.compile("src/CameraNode.py")
py_compile.compile("src/stat.py")

fZip = zipfile.ZipFile("wotstat.zip", "w")
fZip.write("src/__init__.pyc", WOTVersion+"/scripts/client/mods/__init__.pyc")
fZip.write("src/stat.pyc", WOTVersion+"/scripts/client/mods/stat.pyc")
fZip.write("src/CameraNode.pyc", WOTVersion+"/scripts/client/CameraNode.pyc")
fZip.write("data/language/stat_config_ru.json", WOTVersion+"/scripts/client/mods/stat_config.json")
#fZip.write("data/language/stat_config_en.json", WOTVersion+"/scripts/client/mods/stat_config.json")
fZip.write("data/expected_tank_values.json", WOTVersion+"/scripts/client/mods/wotstat/expected_tank_values.json")
fZip.write("data/bgIcon#FFFFFF.png", WOTVersion+"/scripts/client/mods/wotstat/images/bgIcon#FFFFFF.png")
fZip.write("data/bgIcon#FE0E00.png", WOTVersion+"/scripts/client/mods/wotstat/images/bgIcon#FE0E00.png")
fZip.write("data/bgIcon#FE7903.png", WOTVersion+"/scripts/client/mods/wotstat/images/bgIcon#FE7903.png")
fZip.write("data/bgIcon#F8F400.png", WOTVersion+"/scripts/client/mods/wotstat/images/bgIcon#F8F400.png")
fZip.write("data/bgIcon#60FF00.png", WOTVersion+"/scripts/client/mods/wotstat/images/bgIcon#60FF00.png")
fZip.write("data/bgIcon#02C9B3.png", WOTVersion+"/scripts/client/mods/wotstat/images/bgIcon#02C9B3.png")
fZip.write("data/bgIcon#D042F3.png", WOTVersion+"/scripts/client/mods/wotstat/images/bgIcon#D042F3.png")

fZip.close()
