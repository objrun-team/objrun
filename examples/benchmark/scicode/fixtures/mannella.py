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
    # The linear leapfrog recurrence can be unrolled without changing the
    # trajectory-major Gaussian draw order. Batch at most about 8 MiB of noise.
    dt=t0/steps
    half=.5*dt
    denominator=1+half/taup
    velocity_v=(1-half/taup-omega0**2*half*dt)/denominator
    velocity_x=-omega0**2*dt/denominator
    transition=np.array([[1+half*velocity_x,half*(1+velocity_v)],
                         [velocity_x,velocity_v]])
    noise=np.array([half,1.])*np.sqrt(2*dt/taup)*vrms/denominator
    weights=np.empty(steps+2)
    row=np.array([1.,0.])
    for j in range(steps-1,-1,-1):
        weights[j+2]=row@noise
        row=row@transition
    weights[0]=(row[0]-1)*vrms/omega0
    weights[1]=row[1]*vrms
    total=0.
    batch=max(1,1_000_000//(steps+2))
    for start in range(0,Navg,batch):
        size=min(batch,Navg-start)
        draws=np.random.normal(0.,1.,(size,steps+2))
        displacements=draws@weights
        total+=float(displacements@displacements)
    return total/Navg
