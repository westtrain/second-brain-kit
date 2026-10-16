import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import backup as b


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root, self.dest = self.base / 'source', self.base / 'backups'
        self.dest.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.root)], check=True)
        for k,v in [('user.name','Test'),('user.email','test@example.invalid'),('commit.gpgsign','false'),('core.hooksPath','/dev/null')]:
            b.git(self.root,'config',k,v)
        (self.root/'.gitignore').write_text('.env\n.brain-sync.lock\n')
        (self.root/'note.md').write_text('Committed content')
        b.git(self.root,'add','.')
        b.git(self.root,'commit','-m','fixture')

    def test_restore_working_staged_untracked_and_deleted_files(self):
        (self.root/'note.md').write_text('Staged')
        b.git(self.root,'add','note.md')
        (self.root/'note.md').write_text('Working version')
        (self.root/'new.md').write_text('Pending session')
        (self.root/'.env').write_text('Ignored fixture')
        (self.root/'system').mkdir()
        (self.root/'system/manifest.json').write_text('{}')
        before = b.snapshot(self.root)
        archive=b.create(self.root,self.dest,'personal')
        b.verify(archive,'personal')
        restored=b.restore(archive,self.dest/'restored','personal','0')
        self.assertEqual(b.snapshot(restored),before)
        self.assertFalse((restored/'.env').exists())
        self.assertEqual(b.git(restored,'remote').strip(),b'')
        # Unstaged deletion is preserved in a second snapshot.
        (self.root/'note.md').unlink()
        second=b.create(self.root,self.dest,'personal')
        b.restore(second,self.dest/'deleted','personal','0')
        self.assertFalse((self.dest/'deleted/note.md').exists())

    def test_all_worktrees_and_refs_are_backed_up(self):
        task=self.base/'task'
        b.git(self.root,'worktree','add','-b','task',str(task))
        (task/'pending.md').write_text('Only in task worktree')
        archive=b.create(self.root,self.dest,'work')
        manifest=b.verify(archive,'work')
        self.assertEqual(len(manifest['checkouts']),2)
        selected=next(c for c in manifest['checkouts'] if c['source_path']==str(task))
        restored=b.restore(archive,self.dest/'task-restored','work',selected['id'])
        self.assertEqual((restored/'pending.md').read_text(),'Only in task worktree')
        self.assertEqual(b.refs(restored),b.refs(self.root))

    def test_checksum_corruption_detected_before_restore(self):
        archive=b.create(self.root,self.dest,'personal')
        (archive/'checkouts/0/files/note.md').write_text('Corrupt')
        with self.assertRaises(ValueError):b.restore(archive,self.dest/'bad','personal','0')
        self.assertFalse((self.dest/'bad').exists())

    def test_wrong_scope_and_existing_target_rejected(self):
        archive=b.create(self.root,self.dest,'work')
        with self.assertRaises(ValueError):b.verify(archive,'personal')
        with self.assertRaises(ValueError):b.restore(archive,self.root,'work','0')
        self.assertEqual((self.root/'note.md').read_text(),'Committed content')

    def test_symlink_source_rejected_without_partial_backup(self):
        (self.root/'link.md').symlink_to(self.root/'note.md')
        with self.assertRaises(ValueError):b.create(self.root,self.dest,'personal')
        self.assertEqual(list(self.dest.iterdir()),[])

    def test_failed_bundle_leaves_no_completed_or_partial_backup(self):
        real=b.git
        def fail(root,*args):
            if args[:2]==('bundle','create'):raise OSError('simulated failure')
            return real(root,*args)
        with patch.object(b,'git',side_effect=fail):
            with self.assertRaises(OSError):b.create(self.root,self.dest,'personal')
        self.assertEqual(list(self.dest.iterdir()),[])

    def test_changed_source_aborts_backup(self):
        real=b.snapshot
        count=[0]
        def changing(root):
            count[0]+=1
            if count[0]==2:(root/'note.md').write_text('Concurrent edit')
            return real(root)
        with patch.object(b,'snapshot',side_effect=changing):
            with self.assertRaises(ValueError):b.create(self.root,self.dest,'personal')
        self.assertEqual(list(self.dest.iterdir()),[])

    def test_destinations_must_be_separate_by_scope(self):
        config=self.base/'config.json'
        config.write_text(json.dumps({'personal':str(self.root),'work':str(self.base/'company'),
            'backups':{'personal':str(self.dest),'work':str(self.dest)}}))
        with self.assertRaises(ValueError):b.configuration(config,'personal')

    def test_path_traversal_manifest_is_rejected(self):
        archive=b.create(self.root,self.dest,'personal')
        path=archive/'manifest.json'
        data=json.loads(path.read_text())
        data['checkouts'][0]['files']['../../outside']=0o644
        path.write_text(json.dumps(data))
        (archive/'manifest.sha256').write_text(b.sha(path.read_bytes()))
        with self.assertRaises(ValueError):b.restore(archive,self.dest/'bad','personal','0')
        self.assertFalse((self.dest/'bad').exists())

    def test_manifest_corruption_is_detected(self):
        archive=b.create(self.root,self.dest,'personal')
        path=archive/'manifest.json'
        data=json.loads(path.read_text())
        data['checkouts'][0]['files']['note.md']=0o755
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):b.verify(archive,'personal')


if __name__=='__main__':unittest.main()
