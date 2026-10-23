import sympy as sp

def init_eji_array(energy, energy_vertices):
    energies = [energy, *energy_vertices]
    symbols = {f'e{i}{j}': sp.Symbol(f'e{i}{j}') for i in range(5) for j in range(5)}
    values = {symbols[f'e{i}{j}']: float(energies[j] - energies[i]) for i in range(5) for j in range(5)}
    return symbols, values

def integrate_DOS(energy,energy_vertices):
    vertices=sorted(float(x) for x in energy_vertices)
    if energy<=vertices[0] or energy>=vertices[-1]:return 0.
    total=0.
    for i,e in enumerate(vertices):
        denominator=1.
        for j,other in enumerate(vertices):
            if j!=i:denominator*=other-e
        total+=max(energy-e,0.)**2/denominator
    # Uniform tetrahedron density: 6 times the simplex surface integral.
    return float(max(0.,3*total))
