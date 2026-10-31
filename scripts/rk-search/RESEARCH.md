# Source audit and comparison boundary

Sources checked 2026-10-30, prior to interpreting search results.

* Bazavov, *2N-storage Runge-Kutta methods: Order conditions, general properties
  and some analytic solutions*, BIT (2026), DOI
  https://doi.org/10.1007/s10543-026-01139-3 . Publisher HTML and Table 8 HTML
  are saved and hashed. Table 8 prints a51=12053/11172; forward recurrence
  from its published A_i,B_i gives 2053/11172. All other tableau entries,
  weights and nodes match. Printed row sum is 10187/5586 instead of 13/14.
  The reconstructed tableau satisfies all four order<=3 equations exactly.
  The paper itself describes its rational examples as illustrative, not an
  exhaustive optimization of the >2 million rational schemes mentioned there.
* NodePy, https://nodepy.readthedocs.io/en/latest/ and pinned GitHub source
  https://github.com/ketch/nodepy . `error_coefficient` returns
  (elementary_weight - 1/tree.density())/tree.symmetry(). Baseline uses the
  unmodified numerical modules directly; the package initializer's optional
  plotting imports were avoided because host matplotlib has a NumPy ABI issue.
  All four exact coefficients were compared to the independent checker.
* RK-Opt, https://github.com/ketch/RK-Opt , pinned clone. Its low-storage
  `oc_lowstorage.m` checks b*c^2 as well as b*A*c and all nonlinear fourth-order
  trees. The package separates stability polynomial optimization from
  coefficient realization. No MATLAB optimization run is claimed here.
* Carpenter & Kennedy, NASA-TM-109111 (1994),
  https://ntrs.nasa.gov/citations/19940029698 : third-order 2N schemes with error
  control. The family described is four-stage, so it is not a same-stage,
  same-polynomial comparator for this experiment.
* Higueras & Roldan, *New third order low-storage SSP explicit Runge-Kutta
  methods*, https://arxiv.org/abs/1809.04807 : five-stage third-order 2N*
  methods. The 2N* representation retains the old solution and is a different
  low-storage class from the Williamson recurrence fixed here. Lower error
  constants or better SSP coefficients in that class are not evidence about
  this fixed feasible set.
* Ranocha et al., *Optimized Runge-Kutta Methods with Automatic Step Size
  Control for Compressible Computational Fluid Dynamics*,
  https://doi.org/10.1007/s42967-021-00159-w : optimized low-storage methods
  and practical efficiency comparisons. Its investigated 3S* families and
  error-estimator storage are not interchangeable with the fixed 2N task.

This is a bounded literature check, not a systematic priority proof. A candidate
can improve the corrected Table 8 example without being the best general RK(5,3)
method. Equality of stability polynomials must be checked before calling any
published method a comparator in the exact feasible set. The fixed chain-tree
coefficient gives a universal objective lower bound 639/45752; claiming its
attainment requires further verification, not just a floating-point optimizer's
success flag. No single campaign can establish a causal framework comparison.
