from pathlib import Path
p=Path(__file__).parent
s=(p/'compress_individually_closed_prior_v2.next.py').read_text(encoding='utf-8')
s=s.replace('rows=[];closures=[]','rows=[];closures=[];logical=0')
s=s.replace('seen_files.add(st.st_ino);before=allocated(p);digest=sha(p)', 'seen_files.add(st.st_ino)\n  if len(rows)>=24 or logical+st.st_size>768*1024**2:continue\n  logical+=st.st_size;before=allocated(p);digest=sha(p)')
s=s.replace("['compact.exe','/C','/I','/Q',str(p)]", "['compact.exe','/C','/F','/EXE:LZX','/I','/Q',str(p)]")
s=s.replace("HOME/'individually-closed-prior-compression'", "HOME/'individually-closed-prior-lzx-compression'")
s=s.replace('individuallyClosedPriorCompressionPin=pin','individuallyClosedPriorLzxCompressionPin=pin')
target=p/'compress_individually_closed_prior_lzx_v3.next.py'
assert not target.exists()
target.write_text(s,encoding='utf-8')
print(target)
