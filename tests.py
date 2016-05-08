import itertools
import signal
import socket
import subprocess
import sys
import time
import unittest
from contextlib import closing, contextmanager
from random import randint

FIRST_PORT = randint(30000, 40000)
port_iterable = itertools.count(FIRST_PORT)

QUANT_SECONDS = 0.1
MAX_MESSAGE_LEN = 1000


def run_client(port, pipe_stderr: bool=False):
    stderr = subprocess.PIPE if pipe_stderr else None
    return subprocess.Popen(["../zad1/client", "127.0.0.1", str(port)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)


def run_server(port):
    return subprocess.Popen(["../zad1/server", str(port)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)


@contextmanager
def server(port):
    p = run_server(port)
    try:
        time.sleep(QUANT_SECONDS)
        yield p
    finally:
        p.terminate()
        p.stdout.close()
        p.stdin.close()
        p.wait()


@contextmanager
def client(port):
    c = run_client(port)
    try:
        yield c
    finally:
        c.stdout.close()
        c.stdin.close()
        c.wait()


@contextmanager
def mock_server(port):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", port))
        s.listen()
        yield s


@contextmanager
def mock_client(port):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.connect(("127.0.0.1", port))
        yield s


def prepare_message(text: bytes):
    return socket.htons(len(text)).to_bytes(2, sys.byteorder) + text


class TestServer(unittest.TestCase):

    def test_control_c(self):
        """Server should terminate after SIGINT."""
        with server(next(port_iterable)) as p:
            time.sleep(QUANT_SECONDS)
            p.send_signal(signal.SIGINT)
            ret = p.wait()
            self.assertIn(ret, [-2, 2])

    def test_pass_message(self):
        port = next(port_iterable)

        with server(port), mock_client(port) as a, mock_client(port) as b:
            msg = prepare_message(b"blah")
            a.sendall(msg)
            received = b.recv(6)
            assert received == msg

    def test_message_too_long(self):
        port = next(port_iterable)

        with server(port), mock_client(port) as a:
            msg = prepare_message(b"w" * 1001)
            self.assertFalse(self.isSocketClosed(a))
            a.sendall(msg)
            self.assertSocketClosed(a)

    def assertSocketClosed(self, a: socket.socket):
        is_closed = self.isSocketClosed(a)

        if not is_closed:
            raise Exception("Connection alive, expected closed")

    def isSocketClosed(self, a):
        timeout = a.gettimeout()
        a.settimeout(QUANT_SECONDS)
        try:
            msg = a.recv(1)
        except socket.timeout:
            is_closed = False
        else:
            is_closed = True
            if msg != b"":
                raise Exception("Empty socket expected, received '{}'".format(str(msg)))
        a.settimeout(timeout)
        return is_closed

    def test_message_with_endline(self):
        port = next(port_iterable)

        with server(port), mock_client(port) as a:
            a.sendall(prepare_message(b"asdfsafad\nsdfsdf"))
            self.assertSocketClosed(a)

    def test_message_with_zero(self):
        port = next(port_iterable)

        with server(port), mock_client(port) as a:
            a.sendall(prepare_message(b"asdfsafad\0sdfsdf"))
            self.assertSocketClosed(a)

    def test_client_block(self):
        """Checks if messages are passed while one of the client makes a pause during
        sending another message."""
        port = next(port_iterable)

        with server(port), mock_client(port) as a, mock_client(port) as b, \
                mock_client(port) as c:
            message_wrong = prepare_message(b"xxxxx")[:5]
            a.sendall(message_wrong)
            self.assertFalse(self.isSocketClosed(a))
            message_correct = prepare_message(b"yyyy")
            b.sendall(message_correct)
            received = c.recv(len(message_correct))
            self.assertEqual(received, message_correct)

    def test_pass_empty_message(self):
        port = next(port_iterable)
        with server(port), mock_client(port) as a, mock_client(port) as b:
            message = prepare_message(b"")
            a.sendall(message)
            received = b.recv(10)
            self.assertEqual(message, received)


class TestClient(unittest.TestCase):
    def test_break_server(self):
        """Client should finish after server closes connection."""
        port = next(port_iterable)

        with mock_server(port) as s, client(port) as p:
            with s.accept()[0]:
                self.assertIsNone(p.poll())

        ret = p.wait()
        self.assertEqual(ret, 0)

    def test_end_input(self):
        """Client should disconnect after EOF."""
        port = next(port_iterable)
        with mock_server(port) as s, client(port) as p:
            with s.accept()[0]:
                self.assertIsNone(p.poll())
                p.stdin.close()
                self.assertEqual(p.wait(), 0)

    def test_too_long_message_from_server(self):
        """Checks if the client finishes with error code and leaves
        something on stderr.
        """
        port = next(port_iterable)
        with mock_server(port) as s:
            p = run_client(port, pipe_stderr=True)

            with s.accept()[0] as k:
                k.sendall(prepare_message(b"1" * 1001))
                p.wait()
                _, err = p.communicate(b"")
                self.assertIn(b"\n", err)
                self.assertEqual(p.returncode, 100)

    def test_receive_empty_message(self):
        """Checks if empty lines are received and printed."""
        port = next(port_iterable)
        with mock_server(port) as s, client(port) as p:
            with s.accept()[0] as k:
                k.sendall(prepare_message(b""))
                time.sleep(QUANT_SECONDS)
                self.assertIsNone(p.poll())
                out, _ = p.communicate(b"")
                self.assertEqual(out, b"\n")
                p.wait()
                self.assertEqual(p.returncode, 0)

    def test_receive_empty_message_after_nonempty(self):
        """Sends nonempty message first and then an empty one to check if buffers
        are cleaned.
        """
        port = next(port_iterable)
        with mock_server(port) as s, client(port) as p:
            with s.accept()[0] as k:
                messages = [
                    prepare_message(b"blahblah"),
                    prepare_message(b"")
                ]
                k.sendall(messages[0])
                k.sendall(messages[1])
                time.sleep(QUANT_SECONDS)
                self.assertIsNone(p.poll())
                out, _ = p.communicate(b"")
                self.assertEqual(out, b"blahblah\n\n")

    def test_read_message_too_long(self):
        """Checks if message is split correctly."""
        port = next(port_iterable)
        with mock_server(port) as s, client(port) as c:
            with s.accept()[0] as k:
                c.communicate(b"a" * (MAX_MESSAGE_LEN + 1))
                sent = k.recv(2000)
                self.assertEqual(sent, prepare_message(b"a" * 1000) + prepare_message(b"a"))
                ret = c.wait()
                self.assertEqual(ret, 0)

    def test_client_max_message(self):
        """Checks if message of maximum length is correctly sent to the server."""
        port = next(port_iterable)
        message = b"a" * MAX_MESSAGE_LEN
        with mock_server(port) as s, client(port) as c:
            with s.accept()[0] as k:
                c.communicate(message + b"\n")
                sent = k.recv(2000)
                self.assertEqual(sent, prepare_message(message))


class TestClientServer(unittest.TestCase):
    def test_pass_message(self):
        port = next(port_iterable)
        with server(port), client(port) as a, client(port) as b:
            clients = [a, b]
            message = b"Unique message\n"
            time.sleep(QUANT_SECONDS)
            clients[0].stdin.write(message)
            clients[0].stdin.flush()
            time.sleep(QUANT_SECONDS)

            out, err = clients[1].communicate("")
            self.assertEqual(out, message)

    def test_pass_message_max(self):
        port = next(port_iterable)
        with server(port), client(port) as a, client(port) as b:
            clients = [a, b]
            message = b"a" * MAX_MESSAGE_LEN + b"\n"
            time.sleep(QUANT_SECONDS)
            clients[0].stdin.write(message)
            clients[0].stdin.flush()
            time.sleep(QUANT_SECONDS)

            out, err = clients[1].communicate("")
            self.assertEqual(out, message)


if __name__ == '__main__':
    unittest.main()
