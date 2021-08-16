"""
       Copyright 2021 Inmanta

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
import logging
import select
import socket
import time
from queue import Empty, Queue
from threading import Thread
from typing import Iterable, List, Match, Optional, Pattern, Tuple

LOGGER = logging.getLogger(__name__)


END_OF_QUEUE = object()


IAC = 255  # Interpret as Command
DONT = 254
DO = 253
WONT = 252
WILL = 251
NULL = 0

SE = 240
SB = 250


def process_raw_data(raw_sequence: Iterable[int], socket: socket.socket) -> Iterable[int]:
    sub_negotiation = False
    while True:
        next_byte = next(raw_sequence, END_OF_QUEUE)
        if next_byte == END_OF_QUEUE:
            # We are done
            break

        assert isinstance(next_byte, int)
        if next_byte == IAC:
            # Interpret as Command
            cmd = next(raw_sequence)
            if cmd in (DO, DONT):
                # We deny any option
                option = next(raw_sequence)
                socket.sendall(bytes([IAC, WONT, option]))

            if cmd in (WILL, WONT):
                # We deny any option
                option = next(raw_sequence)
                socket.sendall(bytes([IAC, DONT, option]))

            if cmd == IAC:
                # This is not a command but the character escaped
                yield IAC

            if cmd == SB:
                # We should ignore any byte up to the next SE
                sub_negotiation = True

            if cmd == SE:
                # We can stop ignoring bytes
                sub_negotiation = False

            # We ignore any other command
            continue

        if sub_negotiation:
            # We ignore sub negotiations
            continue

        yield next_byte


def logs_consumer(
    logger: logging.Logger,
    log_level: int,
    logs_queue: Queue,
    newline: str,
) -> None:
    remainder = ""
    while True:
        # We wait for the newt element in the queue
        data = logs_queue.get(block=True)

        # If the element is the end of queue, we stop
        if data == END_OF_QUEUE:
            break

        assert isinstance(data, str)

        # Prepend the new elements with the remainder from before
        text = remainder + data

        # Split line by line
        lines = text.split(newline)
        if lines:
            # The last line is not finished
            remainder = lines[-1]
            lines = lines[:-1]
        else:
            remainder = ""

        # Logging each complete lines
        for line in lines:
            logger.log(level=log_level, msg=line.strip())

    # End of the log queue, we log anything we have left
    logger.log(level=log_level, msg=remainder + "EOF")


def connection_producer(
    sock: socket.socket,
    input_queue: Queue,
    logs_queue: Queue,
    encoding: str,
) -> None:
    while sock.fileno() != -1:
        try:
            data = input_queue.get(block=True, timeout=1)
        except Empty:
            # Timeout reached
            continue

        assert isinstance(data, str)

        # Whatever we send should be logged
        logs_queue.put(data)

        data = data.encode(encoding=encoding)
        sent = sock.send(data)
        while sent:
            data = data[sent:]
            sent = sock.send(data)

    # Send an end of queue
    logs_queue.put(END_OF_QUEUE)


def connection_consumer(
    sock: socket.socket,
    output_queue: Queue,
    logs_queue: Queue,
    encoding: str,
) -> None:
    while sock.fileno() != -1:
        # We only pass one socket, once the selct call unblock, there is something
        # to read on the socket
        readables, _, _ = select.select([sock], [], [], 1)
        if not readables:
            # No readable socket --> timeout reached
            continue

        raw_data = sock.recv(4096)
        if not raw_data:
            # The host has closed its port
            break

        data = bytes(list(process_raw_data(iter(raw_data), sock)))

        # Decoding byte data from socket
        text = data.decode(encoding=encoding)

        # Sending the data to the queues
        output_queue.put(text)
        logs_queue.put(text)

    # The socket is closed
    # We mark the end of the output stream
    output_queue.put(END_OF_QUEUE)
    logs_queue.put(END_OF_QUEUE)


class TelnetClient:
    def __init__(
        self, host: str, port: int, log_level: int = logging.DEBUG, newline: str = "\n", encoding: str = "utf-8"
    ) -> None:
        self.host = host
        self.port = port

        self.logger = logging.getLogger(f"telnet[{self.host}:{self.port}]")
        self.log_level = log_level

        self.newlines = (newline,)
        self.encoding = encoding

        self._socket: Optional[socket.socket] = None

        self._receiver_thread: Optional[Thread] = None
        self._sender_thread: Optional[Thread] = None
        self._logs_thread: Optional[Thread] = None

        self._receiver_queue: Optional[Queue] = None
        self._sender_queue: Optional[Queue] = None
        self._logs_queue: Optional[Queue] = None

        self._unconsumed = ""  # Any remainder of line reading operations
        self._readable = False  # Indicate whether we reached the end of the receiver queue

    @property
    def closed(self) -> bool:
        return self._socket is None

    def open(self, timeout: int = 10) -> None:
        if not self.closed:
            raise RuntimeError("Can not open a connection that is already open")

        self._socket = socket.create_connection(
            address=(self.host, self.port),
            timeout=timeout,
        )

        self._logs_queue = Queue()
        self._logs_thread = Thread(
            target=logs_consumer,
            args=(
                self.logger,
                self.log_level,
                self._logs_queue,
                self.newlines[0],
            ),
        )
        self._logs_thread.start()

        self._receiver_queue = Queue()
        self._receiver_thread = Thread(
            target=connection_consumer,
            args=(
                self._socket,
                self._receiver_queue,
                self._logs_queue,
                self.encoding,
            ),
        )
        self._receiver_thread.start()

        self._sender_queue = Queue()
        self._sender_thread = Thread(
            target=connection_producer,
            args=(
                self._socket,
                self._sender_queue,
                self._logs_queue,
                self.encoding,
            ),
        )
        self._sender_thread.start()

        self._readable = True

    def close(self) -> None:
        if self.closed:
            raise RuntimeError("Can not close a connection that is not open")

        # self._socket.shutdown(socket.SHUT_RDWR)
        self._socket.close()
        self._socket = None

        if self._receiver_thread:
            self._receiver_thread.join(5)
            if self._receiver_thread.is_alive():
                LOGGER.warning("Failed to join connection consumer thread")

        if self._sender_thread:
            self._sender_thread.join(5)
            if self._sender_thread.is_alive():
                LOGGER.warning("Failed to join connection producer thread")

        if self._logs_thread:
            self._logs_thread.join(5)
            if self._logs_thread.is_alive():
                LOGGER.warning("Failed to join connection producer thread")

        del self._receiver_queue
        self._receiver_queue = None

        del self._sender_queue
        self._sender_queue = None

        del self._logs_queue
        self._logs_queue = None

    def write(self, s: str) -> None:
        self._sender_queue.put(s)

    def __accumulate_stream(self, timeout: Optional[int] = None) -> Iterable[str]:
        """
        Consume the receiver queue lazily.  Each generated value contains all unconsumed data up
        to the last value we received from the queue.

        :raises TimeoutError: If the timeout expires
        :raises EOFError: If we reached the end of the stream
        """
        data = ""
        next_data = self._unconsumed

        start = time.time()
        while next_data != END_OF_QUEUE:
            assert isinstance(next_data, str)

            data += next_data
            self._unconsumed = data

            yield data

            time_remaining = timeout
            if time_remaining is not None:
                time_remaining -= time.time() - start

            if time_remaining is not None and time_remaining <= 0:
                raise TimeoutError("Timeout error while waiting for matching string")

            if not self._readable:
                # In case we reached the end of the stream before
                # We break out of the loop
                next_data = END_OF_QUEUE
                continue

            try:
                next_data = self._receiver_queue.get(timeout=time_remaining)
            except Empty:
                raise TimeoutError("Timeout error while waiting for matching string")

        self._readable = False
        raise EOFError("Reached the end of the connection stream")

    def read_until(self, match: str, timeout: Optional[int] = None) -> str:
        offset = 0
        for data in self.__accumulate_stream(timeout=timeout):
            matching_index = data.find(match, offset)
            if matching_index != -1:
                matching_index += len(match)
                self._unconsumed = data[matching_index:]
                return data[:matching_index]

            offset = len(data) - len(match)
            offset = max(offset, 0)

    def read_all(self) -> str:
        data = ""
        next_data = self._unconsumed

        while next_data != END_OF_QUEUE:
            assert isinstance(next_data, str)
            data += next_data

            if not self._readable:
                # In case we reached the end of the stream before
                # We break out of the loop
                next_data = END_OF_QUEUE
                continue

            next_data = self._receiver_queue.get()

        self._readable = False
        self._unconsumed = ""
        return data

    def expect(self, expressions: List[Pattern], timeout: Optional[int] = None) -> Tuple[Pattern, Match, str]:
        for data in self.__accumulate_stream(timeout=timeout):
            for pattern in expressions:
                match = pattern.search(data)
                if match:
                    end = match.end()
                    self._unconsumed = data[end:]
                    return pattern, match, data[:end]

    def __enter__(self) -> "TelnetClient":
        self.open()
        return self

    def __exit__(self, *args) -> None:
        self.close()
