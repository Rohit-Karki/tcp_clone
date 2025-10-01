def recv_async(self):
        while not self.closed:
            try:
                data, addr = self.socket.recvfrom()
                if data is not None and data != b'':
                    packet = TCPpacket()
                    packet.unpack(data)

                    if packet.ack:
                        # this packet is an ACK packet so we can send the next packet
                        self.send
                        if packet.sequence_no not in self.receive_buffer:
                            # It means that we have not received this packet before
                            self.receive_buffer[packet.sequence_no] = packet

                    print(f"{self.receive_buffer}")
            except Exception as e:
                print("listener died!")
                print(e)



    def send_ack(self, ack_sequence_np: int):
        packet = TCPpacket(sequence_no=ack_sequence_np, ack=True)
        self.socket.sendto(packet.pack(), (self.dst_ip, self.dst_port))