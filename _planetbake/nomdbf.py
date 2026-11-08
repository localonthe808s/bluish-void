import zipfile, struct, sys
def dbf(path):
    z=zipfile.ZipFile(path); n=[x for x in z.namelist() if x.endswith('.dbf')][0]; b=z.read(n)
    nrec,hlen,rlen=struct.unpack('<IHH',b[4:12]); fields=[]; i=32
    while b[i]!=0x0D:
        nm=b[i:i+11].split(b'\0')[0].decode(); ln=b[i+16]; fields.append((nm,ln)); i+=32
    out=[]; p=hlen
    for r in range(nrec):
        rec=b[p+1:p+rlen]; p+=rlen; o={}; q=0
        for nm,ln in fields: o[nm]=rec[q:q+ln].decode('utf-8','replace').strip(); q+=ln
        out.append(o)
    return out
