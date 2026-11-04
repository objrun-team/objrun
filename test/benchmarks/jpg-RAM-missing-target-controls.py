"""Synthetic Docker missing-target response formats; no Docker run."""
import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/benchmark-repair'))
import jpg_private_ram_executor as e

class Controls(unittest.TestCase):
    def test_01_docker_missing_container_and_volume_formats(self):
        container = 'objrun-jpg-private-' + 'a' * 32
        volume = 'objrun-jpg-ram-' + 'b' * 32
        for kind, target, message in [
            ('container', container, f'Error response from daemon: No such container: {container}\n'),
            ('volume', volume, f'Error response from daemon: get {volume}: no such volume\n'),
        ]:
            with self.subTest(kind=kind):
                self.assertTrue(e.missing_target(1, b'[]\n', message.encode(), kind, target))
    def test_02_word_case_compatible_target_exact(self):
        target='objrun-jpg-private-'+'a'*32;line=('error response from daemon: no such container: '+target+'\n').encode()
        self.assertTrue(e.missing_target(1,b'[]\n',line,'container',target))
        self.assertFalse(e.missing_target(1,b'[]\n',line.replace(target.encode(),target.upper().encode()),'container',target))
        self.assertTrue(e.missing_target(1,b'',('Error: no such object: '+target+'\r\n').encode(),'container',target))
    def test_03_neighbor_extra_items_errors_and_lines_refuse(self):
        target='objrun-jpg-ram-'+'a'*32;line=('Error response from daemon: get '+target+': no such volume\n').encode()
        for out in (b'[{}]\n',b'{"errors":[]}\n',b'[] extra',b'null',b'false',b'\xff'):
            self.assertFalse(e.missing_target(1,out,line,'volume',target))
        for err in (line+b'extra error\n',line+b'\n',line.replace(target.encode(),(target+'-neighbor').encode()),b'permission denied\n',b'Cannot connect to daemon\n'):
            self.assertFalse(e.missing_target(1,b'[]\n',err,'volume',target))
    def test_04_rc_success_and_other_errors_refuse(self):
        target='a'*64;line=('No such object: '+target).encode()
        for rc in (0,2,-1,True,None):self.assertFalse(e.missing_target(rc,b'[]',line,'container',target))
        self.assertFalse(e.missing_target(1,b'[]',line,'image',target))
        self.assertFalse(e.missing_target(1,b'[]',line,'container','foreign'))
    def test_05_positive_negative_absent_before_create_callsite(self):
        p=e.ram.plan('a'*32);o=object.__new__(e.RamOperation);o.plan=p
        target=p['volumeName'];line=('Error response from daemon: get '+target+': no such volume\n').encode()
        o.command=lambda *a,**kw:({'exitCode':1},b'[]\n',line)
        o.absent_before_create('volume',target)
        o.command=lambda *a,**kw:({'exitCode':1},b'[]\n',b'permission denied\n')
        with self.assertRaises(e.GradeFault):o.absent_before_create('volume',target)

if __name__=='__main__':unittest.main(verbosity=2)
