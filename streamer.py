# do not import anything else from loss_socket besides LossyUDP
from lossy_socket import LossyUDP

# do not import anything else from socket except INADDR_ANY
from socket import INADDR_ANY
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from TCPpacket import TCPpacket


class Streamer:
    def __init__(self, dst_ip, dst_port, src_ip=INADDR_ANY, src_port=0):
        """Default values listen on all network interfaces, chooses a random source port,
        and does not introduce any simulated packet loss."""
        self.send_sequence_no = 0
        self.receive_sequence_number = 0

        self.send_buffer = {}  # Packets waiting for ACK: {seq_no: (packet, time_sent)}
        self.receive_buffer = {}  # Received out-of-order packets: {seq_no: packet}
        
        # State flags
        self.self_half_closed = False
        self.remote_closed = False
        self.closed = False
        self.received_fin = False
        
        # Configuration
        self.chunk_size = 1446
        self.time_out_seconds = 0.25
        self.fin_grace_period = 2
        self.default_wait_seconds = 0.01
        
        # Synchronization
        self.lock = threading.Lock()
        self.ack_received = threading.Condition(self.lock)
        
        # Initialize socket
        self.socket = LossyUDP()
        self.socket.bind((src_ip, src_port))
        self.dst_ip = dst_ip
        self.dst_port = dst_port
        
        # Start background threads
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.recv_thread = self.executor.submit(self.recv_async)
        self.retransmit_thread = self.executor.submit(self.retransmit_loop)

    def send(self, data_bytes: bytes) -> None:
        """Send data with pipelined ACKs. Sends all packets and waits for all ACKs."""
        # Chunk the data and send all packets immediately (pipelining)
        chunk_index = 0
        while chunk_index * self.chunk_size < len(data_bytes):
            chunk_start_index = chunk_index * self.chunk_size
            chunk_end_index = min(len(data_bytes), (chunk_index + 1) * self.chunk_size)
            
            packet = TCPpacket(
                sequence_no=self.send_sequence_no,
                data_bytes=data_bytes[chunk_start_index:chunk_end_index],
            )
            
            # Send packet immediately (pipelining - don't wait for ACK)
            time_sent = time.time()
            self.socket.sendto(packet.pack(), (self.dst_ip, self.dst_port))
            
            # Add to send_buffer to track waiting for ACK
            with self.lock:
                self.send_buffer[self.send_sequence_no] = (packet, time_sent)
            
            self.send_sequence_no += 1
            chunk_index += 1
        
        # Wait for all sent packets to be ACKed
        while True:
            with self.lock:
                if len(self.send_buffer) == 0:
                    # All packets ACKed!
                    break
            time.sleep(self.default_wait_seconds)

    def send_ack(self, acknowledgement_number: int):
        """Send an ACK packet for the given sequence number."""
        ack_packet = TCPpacket(sequence_no=acknowledgement_number, ack=True)
        self.socket.sendto(ack_packet.pack(), (self.dst_ip, self.dst_port))
    
    def retransmit_loop(self):
        """Background thread that retransmits packets that have timed out."""
        while not self.closed:
            try:
                with self.lock:
                    to_retransmit = []
                    for seq_no in list(self.send_buffer.keys()):
                        packet, time_sent = self.send_buffer[seq_no]
                        if time.time() - time_sent > self.time_out_seconds:
                            # Packet timed out - needs retransmission
                            to_retransmit.append((seq_no, packet))
                
                # Retransmit outside the lock to avoid holding it too long
                for seq_no, packet in to_retransmit:
                    self.socket.sendto(packet.pack(), (self.dst_ip, self.dst_port))
                    with self.lock:
                        if seq_no in self.send_buffer:  # Check it's still not ACKed
                            self.send_buffer[seq_no] = (packet, time.time())
            except Exception as e:
                print("retransmit_loop died!")
                print(e)
                break
            
            time.sleep(self.default_wait_seconds)
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
        """Background thread that continuously receives packets."""
        while not self.closed:
            try:
                data, addr = self.socket.recvfrom()
                if data is not None and data != b"":
                    packet = TCPpacket()
                    packet.unpack(data)
                    
                    with self.lock:
                        if packet.ack:
                            # Received an ACK - remove packet from send_buffer
                            if packet.sequence_no in self.send_buffer:
                                del self.send_buffer[packet.sequence_no]
                                self.ack_received.notify_all()
                        elif packet.fin:
                            # Received FIN packet
                            self.received_fin = True
                            self.remote_closed = True
                    
                    # Send ACK outside the lock to avoid holding lock too long
                    if packet.ack:
                        pass  # Already handled
                    elif packet.fin:
                        # Send ACK for FIN
                        self.send_ack(acknowledgement_number=packet.sequence_no)
                    else:
                        # Received a data packet - send ACK immediately
                        self.send_ack(acknowledgement_number=packet.sequence_no)
                        # Store packet for in-order delivery
                        with self.lock:
                            if packet.sequence_no not in self.receive_buffer:
                                self.receive_buffer[packet.sequence_no] = packet
            except Exception as e:
                print("recv_async died!")
                print(e)
                break
            time.sleep(self.default_wait_seconds)
        return True

    def close(self) -> None:
        """Cleans up. Implements proper FIN handshake for connection teardown."""
        # Step 1: Wait for all sent data packets to be ACKed
        while True:
            with self.lock:
                if len(self.send_buffer) == 0:
                    break
            time.sleep(self.default_wait_seconds)
        
        # Step 2: Send FIN packet
        fin_packet = TCPpacket(sequence_no=self.send_sequence_no, fin=True)
        time_sent = time.time()
        fin_seq = self.send_sequence_no
        self.send_sequence_no += 1
        
        with self.lock:
            self.send_buffer[fin_seq] = (fin_packet, time_sent)
        
        self.socket.sendto(fin_packet.pack(), (self.dst_ip, self.dst_port))
        
        # Step 3: Wait for ACK of FIN packet (with retries)
        fin_acked = False
        while not fin_acked:
            with self.lock:
                # Check if FIN was ACKed
                if fin_seq not in self.send_buffer:
                    fin_acked = True
                    break
                
                # Check for timeout
                packet, sent_time = self.send_buffer[fin_seq]
                if time.time() - sent_time > self.time_out_seconds:
                    # Resend FIN
                    self.socket.sendto(fin_packet.pack(), (self.dst_ip, self.dst_port))
                    self.send_buffer[fin_seq] = (fin_packet, time.time())
            
            time.sleep(self.default_wait_seconds)
        
        # Step 4: Wait until we receive FIN from other side
        self.self_half_closed = True
        while not self.remote_closed:
            time.sleep(self.default_wait_seconds)
        
        # Step 5: Wait grace period (allow for potential retransmission of FIN ACK)
        time.sleep(self.fin_grace_period)
        
        # Step 6: Stop threads
        self.closed = True
        self.socket.stoprecv()
        
        # Step 7: Shutdown executor
        self.executor.shutdown(wait=True)
