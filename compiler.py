import py_compile, zipfile, os

WOTVersion = "0.9.0"

if os.path.exists("wotstat.zip"):
    os.remove("wotstat.zip")

py_compile.compile("src/__init__.py")
py_compile.compile("src/CameraNode.py")
py_compile.compile("src/stat.py")

fZip = zipfile.ZipFile("wotstat.zip", "w")
fZip.write("src/__init__.pyc", WOTVersion+"/scripts/client/mods/__init__.pyc")
fZip.write("src/stat.pyc", WOTVersion+"/scripts/client/mods/stat.pyc")
fZip.write("src/CameraNode.pyc", WOTVersion+"/scripts/client/CameraNode.pyc")
fZip.write("data/expected_tank_values.json", WOTVersion+"/scripts/client/mods/expected_tank_values.json")
fZip.write("data/stat_config.json", WOTVersion+"/scripts/client/mods/stat_config.json")
fZip.close()
