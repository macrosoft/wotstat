import BigWorld

class CameraNode(BigWorld.UserDataObject):

    def __init__(self):
        BigWorld.UserDataObject.__init__(self)


def load_mods():
    import ResMgr, os, glob
    res = ResMgr.openSection('../paths.xml')
    sb = res['Paths']
    vals = sb.values()[0:2]
    for vl in vals:
        mp = vl.asString + '/scripts/client/mods/*.pyc'
        for fp in glob.iglob(mp):
            _, hn = os.path.split(fp)
            zn, _ = hn.split('.')
            if zn != '__init__':
                print 'Load mods: ' + zn
                try:
                    exec 'import mods.' + zn
                except Exception as err:
                    print 'Load mods Error:' + err


load_mods()
