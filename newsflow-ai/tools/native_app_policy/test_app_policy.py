"""Only new app-policy boundaries, no legacy suite replay."""
from pathlib import Path
import os
import socket
import sqlite3
import subprocess
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from verification_gate import Denied
P=None;WORK=None;BRIDGE=None;RESULTS={}

class PolicyTests(unittest.TestCase):
    def test_01_synthetic_file_roundtrip_and_external_write_denied(self):
        f=WORK/"roundtrip.txt";f.write_text("synthetic",encoding="utf-8")
        self.assertEqual(f.read_text(encoding="utf-8"),"synthetic");f.unlink()
        with self.assertRaises(Denied):(WORK.parent/"outside-probe.txt").write_text("denied")
    def test_02_UNC_ADS_device_relative_and_credential_paths(self):
        for value in (r"\\server\share\data",r"\\.\C:",str(WORK/"file")+":stream",
                      r"..\outside",str(WORK/"key.dpapi")):
            with self.subTest(value=value),self.assertRaises(Denied):P.path(value,write=True)
    def test_03_reparse_inspection_and_link_creation_denied(self):
        path=WORK/"simulated-reparse";original=Path.lstat
        def metadata(item,*a,**k):
            if item==path:return SimpleNamespace(st_file_attributes=0x400)
            return original(item,*a,**k)
        with patch.object(Path,"lstat",metadata):
            with self.assertRaises(Denied):P.path(str(path/"file"),write=True)
        with self.assertRaises(Denied):os.symlink(WORK/"nonexistent",WORK/"denied-link")
    def test_04_registered_SQLite_transaction_close_reopen(self):
        db=WORK/"sqlite-probe.db"
        with sqlite3.connect(str(db)) as c:
            c.execute("create table if not exists probe(id integer primary key, value text)")
            c.execute("insert into probe(value) values ('synthetic')")
        c.close()
        c=sqlite3.connect(str(db))
        self.assertEqual(c.execute("select value from probe").fetchone()[0],"synthetic");c.close()
    def test_05_SQLite_ATTACH_extension_factory_and_URI_denied(self):
        c=sqlite3.connect(str(WORK/"sqlite-probe.db"))
        try:
            for sql in ("ATTACH DATABASE ':memory:' AS other","VACUUM INTO 'not-allowed.db'",
                        "PRAGMA writable_schema=ON"):
                with self.assertRaises(sqlite3.DatabaseError):c.execute(sql)
            with self.assertRaises(Denied):c.set_authorizer(None)
            with self.assertRaises(Denied):c.enable_load_extension(True)
        finally:c.close()
        for value in (str(WORK.parent/"outside.db"),":memory:","file:"+str(WORK/"sqlite-probe.db")):
            with self.assertRaises(Denied):sqlite3.connect(value)
        with self.assertRaises(Denied):sqlite3.connect(str(WORK/"sqlite-probe.db"),factory=sqlite3.Connection)
        with self.assertRaises(Denied):sqlite3.Connection(str(WORK/"sqlite-probe.db"))
    def test_06_owned_literal_loopback_exchange(self):
        with socket.socket() as listener,socket.socket() as client:
            listener.settimeout(1);client.settimeout(1)
            with P.loopback_probe(listener,client):
                listener.bind(("127.0.0.1",0));listener.listen(1)
                address=listener.getsockname();self.assertNotEqual(address[1],8765)
                client.connect(address)
                accepted,_=listener.accept()
                with accepted:
                    client.sendall(b"synthetic");self.assertEqual(accepted.recv(9),b"synthetic")
            RESULTS["loopback_probe_port"]=address[1]
    def test_07_operating_port_external_DNS_proxy_and_unowned_loopback_denied(self):
        for address in (("127.0.0.1",8765),("127.0.0.1",18765),("198.51.100.1",443),("::1",18765)):
            with socket.socket() as s,self.assertRaises(Denied):s.connect(address)
        with self.assertRaises(Denied):socket.getaddrinfo("example.invalid",443)
        with socket.socket(type=socket.SOCK_DGRAM) as s,self.assertRaises(Denied):s.sendto(b"x",("127.0.0.1",53))
    def test_08_process_and_background_thread_denied(self):
        with self.assertRaises((Denied,PermissionError)):subprocess.Popen([str(WORK/"not-approved.exe")],cwd=WORK)
        with self.assertRaises(Denied):threading.Thread(target=lambda:None).start()
        import _thread
        with self.assertRaises(Denied):_thread.start_new_thread(lambda:None,())
    def test_09_actual_FileLock_in_app_data_directory(self):
        from filelock import FileLock
        lock=FileLock(BRIDGE.register_path("smoke"))
        with lock.acquire(timeout=0):self.assertTrue(lock.is_locked)
        self.assertFalse(lock.is_locked)
        RESULTS["actual_FileLock"]=True
