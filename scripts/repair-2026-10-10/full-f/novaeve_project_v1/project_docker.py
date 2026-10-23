"""Explicitly authorized project client; never uses a shared Docker daemon."""
import os
import sys
from manage import DATA,SOCKET,environment,info

ALLOWED={'info','version','pull','build','create','start','exec','inspect','stop','rm','ps','logs','cp','image','volume','network','wait','commit','save','load'}

def main():
    args=sys.argv[1:]
    if not args or args[0] not in ALLOWED:raise SystemExit('project Docker command required; global CLI options denied')
    info()  # Exact socket, DockerRootDir, storage driver and host mounts checked.
    os.execve('/usr/bin/docker',['docker','--host','unix://'+str(SOCKET),*args],environment())

if __name__=='__main__':main()
