import numpy as np

def harmonic_mannella_leapfrog(x0,v0,t0,steps,taup,omega0,vrms):
    dt=t0/steps;x=float(x0);v=float(v0)
    stochastic_scale=np.sqrt(2/taup)*vrms
    for _ in range(steps):
        middle=x+.5*dt*v
        noise=np.random.normal(0.,np.sqrt(dt))
        v=(v-.5*dt*v/taup-omega0**2*middle*dt+stochastic_scale*noise)/(1+.5*dt/taup)
        x=middle+.5*dt*v
    return x

def calculate_msd(t0,steps,taup,omega0,vrms,Navg):
    squared=[]
    for _ in range(Navg):
        x0=np.random.normal(0.,vrms/omega0)
        v0=np.random.normal(0.,vrms)
        end=harmonic_mannella_leapfrog(x0,v0,t0,steps,taup,omega0,vrms)
        squared.append((end-x0)**2)
    return float(np.mean(squared))
