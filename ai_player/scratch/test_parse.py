
def parse_line(line):
    msg_idx = line.find(' :')
    if msg_idx != -1:
        header = line[:msg_idx].split()
        msg = line[msg_idx + 2:].strip()
    else:
        header = line.split()
        msg = ""
    
    if not header: return None, None, None, None
    
    if header[0].startswith(':'):
        source_full = header[0][1:]
        command = header[1] if len(header) > 1 else ""
        target = header[2] if len(header) > 2 else ""
    else:
        source_full = ""
        command = header[0]
        target = header[1] if len(header) > 1 else ""
    
    source_nick = source_full.split('!')[0].lower() if source_full else ""
    return source_nick, command, target, msg

line = ":xArenaManager!manager@host NOTICE TestBot :[SYS_PAYLOAD] {\"token\": \"2da81c5c-fa1c-4903-b8b9-f65fe1202cda\", \"bio\": \"TestHound, a wetware technician\", \"stats\": {\"cpu\": 5, \"ram\": 5, \"bnd\": 5, \"sec\": 5, \"alg\": 5}, \"inventory\": [\"Basic_Ration\"]}"
sn, cmd, tgt, m = parse_line(line)
print(f"Source: {sn}")
print(f"Command: {cmd}")
print(f"Target: {tgt}")
print(f"Msg: {m}")
print(f"Starts with [SYS_PAYLOAD]: {m.startswith('[SYS_PAYLOAD]')}")
