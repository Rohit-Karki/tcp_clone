# do not import anything else from loss_socket besides LossyUDP
from lossy_socket import LossyUDP

# do not import anything else from socket except INADDR_ANY
from socket import INADDR_ANY
import time
from concurrent.futures import ThreadPoolExecutor
from TCPpacket import TCPpacket


class Streamer:
    send_seqeunce_no = 0
    receive_sequence_number = 0

    send_buffer = {}
    receive_buffer = {}

    self_half_closed = False
    remote_closed = False
    closed = False

    executor = None
    recv_thread = None
    send_thread = None

    chunk_size = 1446
    time_out_seconds = 0.25
    fin_grace_period = 2
    default_wait_seconds = 0.001

    def __init__(self, dst_ip, dst_port, src_ip=INADDR_ANY, src_port=0):
        """Default values listen on all network interfaces, chooses a random source port,
        and does not introduce any simulated packet loss."""
        self.socket = LossyUDP()
        self.socket.bind((src_ip, src_port))
        self.dst_ip = dst_ip
        self.dst_port = dst_port
        self.sequence_no = 0

        self.executor = ThreadPoolExecutor(max_workers=2)
        self.recv_thread = self.executor.submit(self.recv_async)
        self.send_thread = self.executor.submit(self.send_async)

    def send(self, data_bytes: bytes) -> None:
        """Note that data_bytes can be larger than one packet."""
        # Your code goes here!  The code below should be changed!

        chunk_index = 0
        while chunk_index * self.chunk_size < len(data_bytes):
            chunk_start_index = chunk_index * self.chunk_size
            chunk_end_index = min(len(data_bytes), (chunk_index + 1) * self.chunk_size)

            packet = TCPpacket(
                sequence_no=self.send_seqeunce_no,
                data_bytes=data_bytes[chunk_start_index:chunk_end_index],
            )
            # print("sending packet: ", packet.sequence_no)

            self.send_buffer[self.send_seqeunce_no] = (packet, 0)
            self.send_seqeunce_no += 1
            chunk_index += 1

    def send_ack(self, acknowledgement_number: int):
        ack_packet = TCPpacket(
            sequence_no=acknowledgement_number, data_bytes=b"", ack=True
        )
        self.socket.sendto(ack_packet.pack(), (self.dst_ip, self.dst_port))

    def send_async(self):
        while not self.closed:
            try:
                # send to the socket
                copy_buffer = self.send_buffer.copy()
                for val in copy_buffer:
                    if isinstance(copy_buffer[val], tuple):
                        packet, time_sent = copy_buffer[val]
                        # print("Checking packet: ", packet.sequence_no)
                        if time_sent is None:
                            # this means we got an ack for this packet
                            del self.send_buffer[packet.sequence_no]
                        elif time.time() - time_sent > self.time_out_seconds:
                            # But if the packet crosses the timeout then we need to resend
                            self.socket.sendto(
                                packet.pack(), (self.dst_ip, self.dst_port)
                            )
                            self.send_buffer[packet.sequence_no] = (packet, time.time())
                            # now wait for ACK packet from the receiver
            except Exception as e:
                print("listener died!")
                print(e)
        return True

    def recv(self) -> bytes:
        """Blocks (waits) if no data is ready to be read from the connection."""
        while self.receive_sequence_number not in self.receive_buffer:
            # print(f"Waiting for packet: {self.receive_sequence_number}")
            # we need to take out the packets orderwise so we need to wait for that particular packet
            time.sleep(self.default_wait_seconds)
        data = self.receive_buffer[self.receive_sequence_number]
        # print(f"Delivering packet: {data}")
        del self.receive_buffer[self.receive_sequence_number]
        self.receive_sequence_number += 1
        return data.data_bytes

    def recv_async(self):
        while not self.closed:
            try:
                data, addr = self.socket.recvfrom()
                if data is not None and data != b"":
                    packet = TCPpacket()
                    packet.unpack(data)

                    # print("Received packet: ", packet.sequence_no)

                    if packet.ack:
                        # we need to make current send sequence no item of send buffer to be know about its ack
                        self.send_buffer[packet.sequence_no] = (packet, None)
                    else:
                        # this packet is an ACK packet so we can send the next packet
                        self.send_ack(acknowledgement_number=packet.sequence_no)
                        # It means that we have not received this packet before
                        if packet.sequence_no not in self.receive_buffer:
                            self.receive_buffer[packet.sequence_no] = packet

                    # print(f"{self.receive_buffer}")
            except Exception as e:
                print("listener died!")
                print(e)
            time.sleep(self.default_wait_seconds)

        return True

    def close(self) -> None:
        """Cleans up. It should block (wait) until the Streamer is done with all
        the necessary ACKs and retransmissions"""
        # your code goes here, especially after you add ACKs and retransmissions.
        self.closed = True
        self.socket.stoprecv()

        while not self.recv_thread.done():
            self.recv_thread.cancel()
            time.sleep(self.default_wait_seconds)

        self.executor.shutdown()
        pass
