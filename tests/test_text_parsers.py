from pathlib import Path
from vc2godot.ide import parse_ide
from vc2godot.ipl import parse_ipl

def test_ide_ipl(tmp_path):
    ide=tmp_path/'x.ide'; ide.write_text('objs\n1,foo,bar,100.0,0\nend\n')
    ipl=tmp_path/'x.ipl'; ipl.write_text('inst\n1,foo,0,10,20,30,0,0,0,1, -1\nend\n')
    assert parse_ide(ide)[1].model=='foo'
    assert parse_ipl(ipl)[0].z==30
