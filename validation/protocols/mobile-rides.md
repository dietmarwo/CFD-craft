# Mobile rides: protocol before access to measurements

Status: frozen workflow outline, no data opened, no experimental claim.
The R1–R3 synthetic checks do not close V2. A named dataset, lawful terms and
site-specific numerical gates must be supplied before a measured study begins.

Before reading concentration values, register the site/flat-ground screen,
map and street versions, coordinate transforms, building/vegetation assumptions,
source groups and externally supplied reference rates. Freeze sensor calibration,
constituent/bin definitions, units, timestamp/route alignment, riding-speed and
response-time treatment, warm-up, missing-data rules and quality exclusions.
Specify how a co-located station establishes background increments; do not fit
background or alignment on held-out rides.

Partition whole rides/days and wind sectors into training and held-out groups
before inference. Record meteorological station/height/time averaging and the
neutral steady-flow eligibility rules. Preregister observation noise,
within-pass correlation, between-pass dependence, effective sample counts,
systematic floors and the numerical rank threshold. Determine sample size and
numerical/experimental error thresholds from independent calibration or study
requirements, before opening concentration data.

Run cold, bounded native wind preparations, source responses and independent
field audits. Preserve rejected sectors, incomplete runs and exclusions with
their reasons. Freeze route/time budgets and candidate availability before
selection; report rank, ambiguous source combinations and actual optimization
bounds. Never infer individual street rates from a deficient matrix.

Evaluate preregistered rate recovery only where independent reference rates
exist, held-out concentration errors and station/path ratios with uncertainty.
Keep numerical acceptance, code-to-code agreement, measured validation and
physical generalization as separate conclusions. Assess grid and wind/model
sensitivity without silently changing the frozen fit. Record all departures as
new protocol versions rather than changing gates after a failure.
