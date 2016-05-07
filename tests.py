import signal
import subprocess
import unittest
import time
import socket
from contextlib import contextmanager

from random import randint

import sys

PORT = randint(30000, 40000)
QUANT_SECONDS = 0.1


def run_client(port, pipe_stderr: bool=False):
    stderr = subprocess.PIPE if pipe_stderr else None
    return subprocess.Popen(["../ml360314/zadanie1/Debug/client", "127.0.0.1", str(port)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)


def run_server(port):
    return subprocess.Popen(["../ml360314/zadanie1/Debug/server", str(port)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)


@contextmanager
def server(port):
    p = run_server(port)
    time.sleep(QUANT_SECONDS)

    yield p

    p.terminate()
    p.wait()


@contextmanager
def mock_server(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))
        s.listen()
        yield s
    s.close()


@contextmanager
def mock_client(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(("127.0.0.1", port))
        yield s
    s.close()


def prepare_message(text: bytes):
    return socket.htons(len(text)).to_bytes(2, sys.byteorder) + text


class TestServer(unittest.TestCase):
    def test_control_c(self):
        """Server should terminate after SIGINT."""
        p = run_server(PORT + 1)
        time.sleep(QUANT_SECONDS)
        p.send_signal(signal.SIGINT)
        ret = p.wait()
        self.assertEqual(ret, -2)

    def test_pass_message(self):
        port = PORT + 7

        with server(port), mock_client(port) as a, mock_client(port) as b:
            msg = prepare_message(b"blah")
            a.sendall(msg)
            received = b.recv(6)
            assert received == msg

    def test_message_too_long(self):
        port = PORT + 8

        with server(port), mock_client(port) as a:
            msg = prepare_message(b"w" * 1001)
            a.settimeout(QUANT_SECONDS)
            with self.assertRaises(socket.timeout):
                a.recv(1)
            a.setblocking(True)
            a.sendall(msg)
            a.settimeout(QUANT_SECONDS)
            self.assertEqual(a.recv(1), b"")


class TestClient(unittest.TestCase):
    def test_break_server(self):
        """Client should finish after server closes connection."""
        with mock_server(PORT + 2) as s:
            p = run_client(PORT + 2)
            k, addr = s.accept()
            self.assertIsNone(p.poll())
            k.shutdown(socket.SHUT_RDWR)
            k.close()
        ret = p.wait()
        self.assertEqual(ret, 0)

    def test_end_input(self):
        """Client should disconnect after EOF."""
        port = PORT + 3
        with mock_server(port) as s:
            p = run_client(port)
            k, addr = s.accept()
            self.assertIsNone(p.poll())
            p.stdin.close()
            self.assertEqual(p.wait(), 0)

    def test_too_long_message_from_server(self):
        """Checks if the client finishes with error code and leaves
        something on stderr.
        """
        port = PORT + 9
        with mock_server(port) as s:
            p = run_client(port, pipe_stderr=True)
            k, addr = s.accept()
            k.sendall(prepare_message(b"1" * 1001))
            p.wait()
            _, err = p.communicate(b"")
            self.assertIn(b"\n", err)
            self.assertEqual(p.returncode, 100)


class TestClientServer(unittest.TestCase):
    def test_pass_message(self):
        port = PORT + 4
        with server(port):
            clients = [run_client(port) for _ in range(2)]
            message = b"Unique message\n"
            time.sleep(QUANT_SECONDS)
            clients[0].stdin.write(message)
            clients[0].stdin.flush()
            time.sleep(QUANT_SECONDS)

            out, err = clients[1].communicate("")
            self.assertEqual(out, message)
            for c in clients:
                c.stdin.close()
                c.wait()


if __name__ == '__main__':
    unittest.main()
