from sys import platform
from typing import Any

import pytest
import numpy as np

from casadi import MX

import biorbd
from bioptim import (
    OptimalControlProgram,
    Dynamics,
    DynamicsList,
    DynamicsFcn,
    ObjectiveList,
    ObjectiveFcn,
    Objective,
    Bounds,
    BoundsList,
    QAndQDotBounds,
    InitialGuessList,
    InitialGuess,
    InterpolationType,
    OdeSolver,
    ConstraintList,
    ConstraintFcn,
    Node,
    PenaltyNode,
    PhaseTransitionList,
    PhaseTransitionFcn,
    ParameterList,
)

from .utils import TestUtils


def custom_func_track_markers(pn: PenaltyNode, first_marker: str, second_marker: str) -> MX:
    # Get the index of the markers
    marker_0_idx = biorbd.marker_index(pn.nlp.model, first_marker)
    marker_1_idx = biorbd.marker_index(pn.nlp.model, second_marker)

    # Store the casadi function. Using add_casadi_func allow to skip if the function already exists
    markers_func = pn.nlp.add_casadi_func("markers", pn.nlp.model.markers, pn.nlp.q)

    # Get the marker positions and compute the difference
    nq = pn.nlp.shape["q"]
    q = pn.x[:nq]
    markers = markers_func(q)
    return markers[:, marker_0_idx] - markers[:, marker_1_idx]


def prepare_ocp_phase_transitions(
    biorbd_model_path: str,
    with_constraints: bool,
    with_mayer: bool,
    with_lagrange: bool,
) -> OptimalControlProgram:
    """
    Parameters
    ----------
    biorbd_model_path: str
        The path to the bioMod

    Returns
    -------
    The ocp ready to be solved
    """

    # Model path
    biorbd_model = (
        biorbd.Model(biorbd_model_path),
        biorbd.Model(biorbd_model_path),
        biorbd.Model(biorbd_model_path),
        biorbd.Model(biorbd_model_path),
    )

    # Problem parameters
    n_shooting = (20, 20, 20, 20)
    final_time = (2, 5, 4, 2)
    tau_min, tau_max, tau_init = -100, 100, 0

    # Add objective functions
    objective_functions = ObjectiveList()
    if with_lagrange:
        objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_TORQUE, weight=100, phase=0)
        objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_TORQUE, weight=100, phase=1)
        objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_TORQUE, weight=100, phase=2)
        objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_TORQUE, weight=100, phase=3)
    if with_mayer:
        objective_functions.add(ObjectiveFcn.Mayer.MINIMIZE_TIME)
        objective_functions.add(ObjectiveFcn.Mayer.MINIMIZE_COM_POSITION, phase=0, node=1)

    # Dynamics
    dynamics = DynamicsList()
    dynamics.add(DynamicsFcn.TORQUE_DRIVEN)
    dynamics.add(DynamicsFcn.TORQUE_DRIVEN)
    dynamics.add(DynamicsFcn.TORQUE_DRIVEN)
    dynamics.add(DynamicsFcn.TORQUE_DRIVEN)

    # Constraints
    constraints = ConstraintList()
    if with_constraints:
        constraints.add(
            ConstraintFcn.SUPERIMPOSE_MARKERS, node=Node.START, first_marker="m0", second_marker="m1", phase=0
        )
        constraints.add(
            ConstraintFcn.SUPERIMPOSE_MARKERS, node=Node.END, first_marker="m0", second_marker="m2", phase=0
        )
        constraints.add(
            ConstraintFcn.SUPERIMPOSE_MARKERS, node=Node.END, first_marker="m0", second_marker="m1", phase=1
        )
        constraints.add(
            ConstraintFcn.SUPERIMPOSE_MARKERS, node=Node.END, first_marker="m0", second_marker="m2", phase=2
        )
        constraints.add(custom_func_track_markers, node=Node.ALL, first_marker="m0", second_marker="m1", phase=3)

    # Path constraint
    x_bounds = BoundsList()
    x_bounds.add(bounds=QAndQDotBounds(biorbd_model[0]))
    x_bounds.add(bounds=QAndQDotBounds(biorbd_model[0]))
    x_bounds.add(bounds=QAndQDotBounds(biorbd_model[0]))
    x_bounds.add(bounds=QAndQDotBounds(biorbd_model[0]))

    x_bounds[0][[1, 3, 4, 5], 0] = 0
    x_bounds[-1][[1, 3, 4, 5], -1] = 0

    x_bounds[0][2, 0] = 0.0
    x_bounds[2][2, [0, -1]] = [0.0, 1.57]

    # Initial guess
    x_init = InitialGuessList()
    x_init.add([0] * (biorbd_model[0].nbQ() + biorbd_model[0].nbQdot()))
    x_init.add([0] * (biorbd_model[0].nbQ() + biorbd_model[0].nbQdot()))
    x_init.add([0] * (biorbd_model[0].nbQ() + biorbd_model[0].nbQdot()))
    x_init.add([0] * (biorbd_model[0].nbQ() + biorbd_model[0].nbQdot()))

    # Define control path constraint
    u_bounds = BoundsList()
    u_bounds.add([tau_min] * biorbd_model[0].nbGeneralizedTorque(), [tau_max] * biorbd_model[0].nbGeneralizedTorque())
    u_bounds.add([tau_min] * biorbd_model[0].nbGeneralizedTorque(), [tau_max] * biorbd_model[0].nbGeneralizedTorque())
    u_bounds.add([tau_min] * biorbd_model[0].nbGeneralizedTorque(), [tau_max] * biorbd_model[0].nbGeneralizedTorque())
    u_bounds.add([tau_min] * biorbd_model[0].nbGeneralizedTorque(), [tau_max] * biorbd_model[0].nbGeneralizedTorque())

    u_init = InitialGuessList()
    u_init.add([tau_init] * biorbd_model[0].nbGeneralizedTorque())
    u_init.add([tau_init] * biorbd_model[0].nbGeneralizedTorque())
    u_init.add([tau_init] * biorbd_model[0].nbGeneralizedTorque())
    u_init.add([tau_init] * biorbd_model[0].nbGeneralizedTorque())

    # Define phase transitions
    phase_transitions = PhaseTransitionList()
    phase_transitions.add(PhaseTransitionFcn.IMPACT, phase_pre_idx=1)
    phase_transitions.add(PhaseTransitionFcn.CONTINUOUS, phase_pre_idx=2, idx_1=1, idx_2=3)
    phase_transitions.add(PhaseTransitionFcn.CYCLIC)

    return OptimalControlProgram(
        biorbd_model,
        dynamics,
        n_shooting,
        final_time,
        x_init,
        u_init,
        x_bounds,
        u_bounds,
        objective_functions,
        constraints,
        phase_transitions=phase_transitions,
    )


def my_parameter_function(biorbd_model: biorbd.Model, value: MX, extra_value: Any):
    value[2] *= extra_value
    biorbd_model.setGravity(value)


def set_mass(biorbd_model: biorbd.Model, value: MX):
    biorbd_model.segment(0).characteristics().setMass(value)


def my_target_function(ocp: OptimalControlProgram, value: MX) -> MX:
    return value


def prepare_ocp_parameters(
    biorbd_model_path,
    final_time,
    n_shooting,
    optim_gravity,
    optim_mass,
    min_g,
    max_g,
    target_g,
    min_m,
    max_m,
    target_m,
    ode_solver=OdeSolver.RK4(),
    use_sx=False,
) -> OptimalControlProgram:
    """
    Prepare the program

    Parameters
    ----------
    biorbd_model_path: str
        The path of the biorbd model
    final_time: float
        The time at the final node
    n_shooting: int
        The number of shooting points
    optim_gravity: bool
        If the gravity should be optimized
    optim_mass: bool
        If the mass should be optimized
    min_g: np.ndarray
        The minimal value for the gravity
    max_g: np.ndarray
        The maximal value for the gravity
    target_g: np.ndarray
        The target value for the gravity
    min_m: float
        The minimal value for the mass
    max_m: float
        The maximal value for the mass
    target_m: float
        The target value for the mass
    ode_solver: OdeSolver
        The type of ode solver used
    use_sx: bool
        If the program should be constructed using SX instead of MX (longer to create the CasADi graph, faster to solve)

    Returns
    -------
    The ocp ready to be solved
    """

    # --- Options --- #
    biorbd_model = biorbd.Model(biorbd_model_path)
    n_tau = biorbd_model.nbGeneralizedTorque()

    # Add objective functions
    objective_functions = ObjectiveList()
    objective_functions.add(ObjectiveFcn.Lagrange.MINIMIZE_TORQUE, weight=10)
    objective_functions.add(ObjectiveFcn.Mayer.MINIMIZE_TIME, weight=10)

    # Dynamics
    dynamics = Dynamics(DynamicsFcn.TORQUE_DRIVEN)

    # Path constraint
    x_bounds = QAndQDotBounds(biorbd_model)
    x_bounds[:, [0, -1]] = 0
    x_bounds[1, -1] = 3.14

    # Initial guess
    n_q = biorbd_model.nbQ()
    n_qdot = biorbd_model.nbQdot()
    x_init = InitialGuess([0] * (n_q + n_qdot))

    # Define control path constraint
    tau_min, tau_max, tau_init = -300, 300, 0
    u_bounds = Bounds([tau_min] * n_tau, [tau_max] * n_tau)
    u_bounds[1, :] = 0

    u_init = InitialGuess([tau_init] * n_tau)

    # Define the parameter to optimize
    parameters = ParameterList()

    if optim_gravity:
        # Give the parameter some min and max bounds
        bound_gravity = Bounds(min_g, max_g, interpolation=InterpolationType.CONSTANT)
        # and an initial condition
        initial_gravity = InitialGuess((min_g + max_g) / 2)
        # and an objective function
        parameter_objective_functions = Objective(
            my_target_function, weight=1000, quadratic=False, custom_type=ObjectiveFcn.Parameter, target=target_g
        )
        parameters.add(
            "gravity_xyz",  # The name of the parameter
            my_parameter_function,  # The function that modifies the biorbd model
            initial_gravity,  # The initial guess
            bound_gravity,  # The bounds
            size=3,  # The number of elements this particular parameter vector has
            penalty_list=parameter_objective_functions,  # ObjectiveFcn of constraint for this particular parameter
            scaling=np.array([1, 1, 10.0]),
            extra_value=1,  # You can define as many extra arguments as you want
        )

    if optim_mass:
        bound_mass = Bounds(min_m, max_m, interpolation=InterpolationType.CONSTANT)
        initial_mass = InitialGuess((min_m + max_m) / 2)
        mass_objective_functions = Objective(
            my_target_function, weight=100, quadratic=False, custom_type=ObjectiveFcn.Parameter, target=target_m
        )
        parameters.add(
            "mass",  # The name of the parameter
            set_mass,  # The function that modifies the biorbd model
            initial_mass,  # The initial guess
            bound_mass,  # The bounds
            size=1,  # The number of elements this particular parameter vector has
            penalty_list=mass_objective_functions,  # ObjectiveFcn of constraint for this particular parameter
            scaling=np.array([10.0]),
        )

    return OptimalControlProgram(
        biorbd_model,
        dynamics,
        n_shooting,
        final_time,
        x_init,
        u_init,
        x_bounds,
        u_bounds,
        objective_functions,
        parameters=parameters,
        ode_solver=ode_solver,
        use_sx=use_sx,
    )


@pytest.mark.parametrize("with_mayer", [True, False])
@pytest.mark.parametrize("with_lagrange", [True, False])
@pytest.mark.parametrize("with_constraints", [True, False])
def test_phase_transitions(with_mayer, with_lagrange, with_constraints):
    if platform == "win32":
        return

    bioptim_folder = TestUtils.bioptim_folder()
    model_path = bioptim_folder + "/examples/getting_started/cube.bioMod"
    ocp = prepare_ocp_phase_transitions(
        model_path, with_mayer=with_mayer, with_lagrange=with_lagrange, with_constraints=with_constraints
    )
    ocp.print(to_console=True, to_graph=True)


def test_parameters():
    if platform == "win32":
        return

    optim_gravity = True
    optim_mass = True
    bioptim_folder = TestUtils.bioptim_folder()
    model_path = bioptim_folder + "/examples/getting_started/pendulum.bioMod"
    ocp = prepare_ocp_parameters(
        biorbd_model_path=model_path,
        final_time=3,
        n_shooting=100,
        optim_gravity=optim_gravity,
        optim_mass=optim_mass,
        min_g=np.array([-1, -1, -10]),
        max_g=np.array([1, 1, -5]),
        min_m=10,
        max_m=30,
        target_g=np.array([0, 0, -9.81]),
        target_m=20,
    )
    ocp.print(to_console=True, to_graph=True)
