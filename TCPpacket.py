import struct

len_sequence_number = 2
len_flags = 1
len_checksum = 16


class TCPpacket:
    sequence_no = None
    data_bytes = None
    checksum = None

    ack = None
    fin = None

    def __init__(self, sequence_no: int = 0, data_bytes: bytes = b'', ack=False, fin=False):
        self.sequence_no = sequence_no
        self.data_bytes = data_bytes
        self.ack = ack
        self.fin = fin

    def pack(self):
        # Add 1 byte for flag
        header_format = 'Hc'  # sequence_no (2 bytes) + flag (1 byte)
        packing_format = header_format + str(len(self.data_bytes)) + 's'
        flags = b'1' if self.ack else (b'2' if self.fin else b'0')

        return struct.pack(packing_format, self.sequence_no, flags, self.data_bytes)

    def unpack(self, packet):
        format = 'Hc' + str(
            len(packet) - len_sequence_number - len_flags) + 's'

        self.sequence_no, flags, self.data_bytes = struct.unpack(
            format, packet)

        self.ack = False
        self.fin = False

        self.ack = flags == b'1'
        self.fin = flags == b'2'
        self.data_bytes = packet[3:]

    def __str__(self):
        return str(self.sequence_no) + '\n' + self.data_bytes.decode(
            'utf-8')
