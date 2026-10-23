import numpy as np
from scipy import integrate,optimize


def f_Schrod(energy,l,r_grid):
    r=np.asarray(r_grid)
    return l*(l+1)/r**2-2/r-energy


def Numerov(f_in,u_at_0,up_at_0,step):
    f=np.asarray(f_in)
    h2=step**2
    inverse=1/(1-h2*f/12)
    u=np.empty(len(f))
    u[0]=u_at_0
    if len(f)==1:
        return u
    previous=(1-h2*f[0]/12)*u_at_0
    current=previous+step*up_at_0
    u[1]=current*inverse[1]
    for i in range(1,len(f)-1):
        following=2*current-previous+h2*f[i]*u[i]
        u[i+1]=following*inverse[i+1]
        previous,current=current,following
    return u


def compute_Schrod(energy,r_grid,l):
    r=np.asarray(r_grid)
    values=Numerov(f_Schrod(energy,l,r[::-1]),0.,-1e-7,r[0]-r[1])[::-1]
    return values/np.sqrt(integrate.simpson(values**2,x=r))


def shoot(energy,r_grid,l):
    r=np.asarray(r_grid)
    u=compute_Schrod(energy,r,l)/r**l
    return float(u[0]-r[0]*(u[1]-u[0])/(r[1]-r[0]))


def _roots(grid,function,l):
    states=[]
    last=float(grid[0]);last_value=function(last)
    for next_energy in grid[1:]:
        next_energy=float(next_energy)
        next_value=function(next_energy)
        if last_value*next_value<0:
            energy=optimize.brentq(function,last,next_energy)
            states.append((l,energy))
            if len(states)==10:
                break
        last,last_value=next_energy,next_value
    return states


def find_bound_states(r_grid,l,energy_grid):
    return _roots(energy_grid,lambda e:shoot(e,r_grid,l),l)


def sort_states(bound_states):
    return sorted(bound_states,key=lambda state:state[1]+state[0]/10000.)


def _populate(bound_states,r_grid,Z,wavefunction):
    r=np.asarray(r_grid)
    charge=np.zeros_like(r,dtype=float)
    remaining=float(Z)
    total_energy=0.
    for l,energy in sort_states(bound_states):
        if remaining<=0:
            break
        degeneracy=2*(2*l+1)
        occupancy=min(remaining,degeneracy)
        u=wavefunction(energy,l)
        charge+=occupancy*u**2/(4*np.pi*r**2)
        total_energy+=occupancy*energy
        remaining-=occupancy
    return charge,total_energy


def calculate_charge_density(bound_states,r_grid,Z):
    return _populate(bound_states,r_grid,Z,
        lambda energy,l:compute_Schrod(energy,r_grid,l))[0]


def calculate_HartreeU(charge_density,u_at_0,up_at_0,step,r_grid,Z):
    source=-8*np.pi*np.asarray(r_grid)*charge_density
    h2=step**2
    u=np.empty(len(source))
    u[0]=u_at_0
    previous=u_at_0-h2*source[0]/12
    current=previous+step*up_at_0
    u[1]=current+h2*source[1]/12
    for i in range(1,len(source)-1):
        following=2*current-previous+h2*source[i]
        u[i+1]=following+h2*source[i+1]/12
        previous,current=current,following
    u+=(2*Z-u[-1])*np.asarray(r_grid)/r_grid[-1]
    return u


def f_Schrod_Hartree(energy,r_grid,l,Z,hartreeU):
    r=np.asarray(r_grid)
    return l*(l+1)/r**2+(hartreeU-2*Z)/r-energy


def compute_Schrod_Hartree(energy,r_grid,l,Z,hartreeU):
    r=np.asarray(r_grid)
    f=f_Schrod_Hartree(energy,r[::-1],l,Z,np.asarray(hartreeU)[::-1])
    values=Numerov(f,0.,-1e-7,r[0]-r[1])[::-1]
    return values/np.sqrt(integrate.simpson(values**2,x=r))


def extrapolate_polyfit(energy,r_grid,l,Z,hartreeU):
    r=np.asarray(r_grid)
    values=compute_Schrod_Hartree(energy,r,l,Z,hartreeU)/r**l
    return float(np.polyfit(r[:4],values[:4],3)[-1])


def find_bound_states_Hartree(r_grid,l,energy_grid,Z,hartreeU):
    return _roots(energy_grid,
        lambda e:extrapolate_polyfit(e,r_grid,l,Z,hartreeU),l)


def calculate_charge_density_Hartree(bound_states,r_grid,Z,hartreeU):
    return _populate(bound_states,r_grid,Z,
        lambda energy,l:compute_Schrod_Hartree(energy,r_grid,l,Z,hartreeU))


def scf_routine(r_grid,energy_grid,nmax,Z,hartreeU,tolerance,iteration):
    r=np.asarray(r_grid)
    potential=np.array(hartreeU,dtype=float,copy=True)
    old_density=None
    old_energy=None
    for _ in range(iteration):
        states=[]
        for l in range(nmax):
            states.extend(find_bound_states_Hartree(r,l,energy_grid,Z,potential))
        charge_density,orbital_energy=calculate_charge_density_Hartree(states,r,Z,potential)
        hartree_energy=integrate.simpson(2*np.pi*r*potential*charge_density,x=r)
        total_energy=float(orbital_energy-hartree_energy)
        if old_energy is not None and abs(total_energy-old_energy)<tolerance:
            break
        if old_density is not None:
            charge_density=.3*charge_density+.7*old_density
        potential=calculate_HartreeU(charge_density,0.,0.,r[1]-r[0],r,Z)
        old_density=charge_density.copy()
        old_energy=total_energy
    return charge_density,total_energy
