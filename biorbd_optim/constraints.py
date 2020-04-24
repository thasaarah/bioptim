import enum
from math import inf

import biorbd
from casadi import vertcat, Function, horzsplit

from .dynamics import Dynamics
from .enums import Instant
from .goal import Goal

# TODO: Convert the constraint in CasADi function?


class Constraint(Goal):
    class Type(enum.Enum):
        """
        Different conditions between biorbd geometric structures.
        """

        MARKERS_TO_MATCH = "markers_to_match"
        ALIGN_WITH_CUSTOM_RT = "align_with_custom_rt"
        PROJECTION_ON_PLANE = "projection_on_plane"
        TRACK_Q = "track_q"
        PROPORTIONAL_Q = "proportional_q"
        PROPORTIONAL_CONTROL = "proportional_control"
        CONTACT_FORCE_GREATER_THAN = "contact_force_greater_than"
        CONTACT_FORCE_LESSER_THAN = "contact_force_lesser_than"
        NON_SLIPPING = "non_slipping"
        CUSTOM = "custom"

    @staticmethod
    def add_constraints(ocp, nlp):
        """
        Adds constraints to the requested nodes in (nlp.g) and (nlp.g_bounds).
        :param ocp: An OptimalControlProgram class.
        """
        if nlp["constraints"] is None:
            return
        for constraint in nlp["constraints"]:
            t, x, u = Constraint._get_instant(nlp, constraint)
            _type = constraint["type"]
            instant = constraint["instant"]
            del constraint["instant"], constraint["type"]
            if _type == Constraint.Type.MARKERS_TO_MATCH:
                Constraint.__markers_to_match(ocp, nlp, x, **constraint)

            elif _type == Constraint.Type.ALIGN_WITH_CUSTOM_RT:
                Constraint.__align_with_custom_rt(ocp, nlp, x, **constraint)

            elif _type == Constraint.Type.PROJECTION_ON_PLANE:
                Constraint.__projection_on_plane_constraint(ocp, nlp, x, **constraint)

            elif _type == Constraint.Type.TRACK_Q:
                Constraint.__q_to_match(ocp, nlp, t, x, **constraint)

            elif _type == Constraint.Type.PROPORTIONAL_Q:
                Constraint.__proportional_variable(ocp, nlp, x, **constraint)

            elif _type == Constraint.Type.PROPORTIONAL_CONTROL:
                if instant == Instant.END or instant == nlp["ns"]:
                    raise RuntimeError("No control u at last node")
                Constraint.__proportional_variable(ocp, nlp, u, **constraint)

            elif _type == Constraint.Type.CONTACT_FORCE_GREATER_THAN:
                if instant == Instant.END or instant == nlp["ns"]:
                    raise RuntimeError("No control u at last node")
                Constraint.__contact_force_inequality(ocp, nlp, x, u, "GREATER_THAN", **constraint)

            elif _type == Constraint.Type.CONTACT_FORCE_LESSER_THAN:
                if instant == Instant.END or instant == nlp["ns"]:
                    raise RuntimeError("No control u at last node")
                Constraint.__contact_force_inequality(ocp, nlp, x, u, "LESSER_THAN", **constraint)

            elif _type == Constraint.Type.NON_SLIPPING:
                if instant == Instant.END or instant == nlp["ns"]:
                    raise RuntimeError("No control u at last node")
                Constraint.__non_slipping(ocp, nlp, x, u, **constraint)

            elif _type == Constraint.Type.CUSTOM:
                func = constraint["function"]
                del constraint["function"]
                func(ocp, nlp, x, u, **constraint)

            else:
                raise RuntimeError(f"{constraint} is not a valid constraint, take a look in Constraint.Type class")

    @staticmethod
    def __markers_to_match(ocp, nlp, X, first_marker, second_marker):
        """
        Adds the constraint that the two markers must be coincided at the desired instant(s).
        :param nlp: An OptimalControlProgram class.
        :param X: List of instant(s).
        :param policy: Tuple of indices of two markers.
        """
        Constraint._check_idx("marker", [first_marker, second_marker], nlp["model"].nbMarkers())

        nq = nlp["q_mapping"].reduce.len
        for x in horzsplit(X, 1):
            q = nlp["q_mapping"].expand.map(x[:nq])
            marker1 = nlp["model"].marker(q, first_marker).to_mx()
            marker2 = nlp["model"].marker(q, second_marker).to_mx()

            ocp.g = vertcat(ocp.g, marker1 - marker2)
            for i in range(3):
                ocp.g_bounds.min.append(0)
                ocp.g_bounds.max.append(0)

    @staticmethod
    def __align_with_custom_rt(ocp, nlp, X, segment, rt):
        """
        Adds the constraint that the RT and the segment must be aligned at the desired instant(s).
        :param nlp: An OptimalControlProgram class.
        :param X: List of instant(s).
        :param policy: Tuple of indices of segment and rt.
        """
        Constraint._check_idx("segment", segment, nlp["model"].nbSegment())
        Constraint._check_idx("rt", rt, nlp["model"].nbRTs())

        nq = nlp["q_mapping"].reduce.len
        for x in horzsplit(X, 1):
            q = nlp["q_mapping"].expand.map(x[:nq])
            r_seg = nlp["model"].globalJCS(q, segment).rot()
            r_rt = nlp["model"].RT(q, rt).rot()
            constraint = biorbd.Rotation_toEulerAngles(r_seg.transpose() * r_rt, "zyx").to_mx()
            ocp.g = vertcat(ocp.g, constraint)
            for i in range(constraint.rows()):
                ocp.g_bounds.min.append(0)
                ocp.g_bounds.max.append(0)

    @staticmethod
    def __projection_on_plane_constraint(ocp, nlp, X, marker, segment, axes):
        if not isinstance(axes, (tuple, list)):
            axes = (axes,)

        nq = nlp["q_mapping"].reduce.len
        for x in horzsplit(X, 1):
            q = nlp["q_mapping"].expand.map(x[:nq])

            r_rt = nlp["model"].globalJCS(q, segment)
            n_seg = nlp["model"].marker(q, marker)
            n_seg.applyRT(r_rt.transpose())
            n_seg = n_seg.to_mx()

            for axe in axes:
                ocp.g = vertcat(ocp.g, n_seg[axe, 0])
                ocp.g_bounds.min.append(0)
                ocp.g_bounds.max.append(0)

    @staticmethod
    def __q_to_match(ocp, nlp, t, x, data_to_track, states_idx=()):
        states_idx = Constraint._check_and_fill_index(states_idx, nlp["nx"], "state_idx")
        data_to_track = Constraint._check_tracking_data_size(data_to_track, [nlp["ns"] + 1, len(states_idx)])

        for idx, v in enumerate(horzsplit(x, 1)):
            ocp.g = vertcat(ocp.g, v[states_idx] - data_to_track[t[idx], states_idx])
            for _ in states_idx:
                ocp.g_bounds.min.append(0)
                ocp.g_bounds.max.append(0)

    @staticmethod
    def __proportional_variable(ocp, nlp, UX, first_dof, second_dof, coef):
        """
        Adds proportionality constraint between the elements (states or controls) chosen.
        :param nlp: An instance of the OptimalControlProgram class.
        :param V: List of states or controls at instants on which this constraint must be applied.
        :param policy: A tuple or a tuple of tuples (also works with lists) whose first two elements
        are the indexes of elements to be linked proportionally.
        The third element of each tuple (policy[i][2]) is the proportionality coefficient.
        """
        Constraint._check_idx("dof", (first_dof, second_dof), UX.rows())
        if not isinstance(coef, (int, float)):
            raise RuntimeError("coef must be an int or a float")

        for v in horzsplit(UX, 1):
            v = nlp["q_mapping"].expand.map(v)
            ocp.g = vertcat(ocp.g, v[first_dof] - coef * v[second_dof])
            ocp.g_bounds.min.append(0)
            ocp.g_bounds.max.append(0)

    @staticmethod
    def __contact_force_inequality(ocp, nlp, X, U, _type, idx, boundary):
        """
        To be completed when this function will be fully developed, in particular the fact that policy is either a tuple/list or a tuple of tuples/list of lists,
        with in the 1st index the number of the contact force and in the 2nd index the associated bound.
        """
        # To be modified later so that it can handle something other than lower bounds for greater than
        CS_func = Function(
            "Contact_force_inequality",
            [ocp.symbolic_states, ocp.symbolic_controls],
            [Dynamics.forces_from_forward_dynamics_with_contact(ocp.symbolic_states, ocp.symbolic_controls, nlp)],
            ["x", "u"],
            ["CS"],
        ).expand()

        X, U = horzsplit(X, 1), horzsplit(U, 1)
        for i in range(len(U)):
            ocp.g = vertcat(ocp.g, CS_func(X[i], U[i])[idx])
            if _type == "GREATER_THAN":
                ocp.g_bounds.min.append(boundary)
                ocp.g_bounds.max.append(inf)
            elif _type == "LESSER_THAN":
                ocp.g_bounds.min.append(-inf)
                ocp.g_bounds.max.append(boundary)

    @staticmethod
    def __non_slipping(ocp, nlp, X, U, normal_component_idx, tangential_component_idx, static_friction_coefficient):
        """
        :param coeff: It is the coefficient of static friction.
        """
        CS_func = Function(
            "Contact_force_inequality",
            [ocp.symbolic_states, ocp.symbolic_controls],
            [Dynamics.forces_from_forward_dynamics_with_contact(ocp.symbolic_states, ocp.symbolic_controls, nlp)],
            ["x", "u"],
            ["CS"],
        ).expand()

        mu = static_friction_coefficient
        X, U = horzsplit(X, 1), horzsplit(U, 1)
        for i in range(len(U)):
            normal_contact_force = tangential_contact_force = 0
            for idx in normal_component_idx:
                normal_contact_force += CS_func(X[i], U[i])[idx]
            for idx in tangential_component_idx:
                normal_contact_force += CS_func(X[i], U[i])[idx]
            # ocp.g = vertcat(ocp.g, tangential_contact_force)
            # if normal_contact_force >= 0:             # Triggers error likely because MX haven't defined value here
            #     ocp.g_bounds.min.append(-mu*normal_contact_force)    # Triggers error likely because MX haven't defined value here
            #     ocp.g_bounds.max.append(mu*normal_contact_force)     # Same
            # else:
            #     ocp.g_bounds.min.append(mu*normal_contact_force)     # Same
            #     ocp.g_bounds.max.append(-mu*normal_contact_force)    # Same

            # Proposal : only case normal_contact_force >= 0 and with two ocp.g
            ocp.g = vertcat(ocp.g, mu * normal_contact_force + tangential_contact_force)
            ocp.g_bounds.min.append(0)
            ocp.g_bounds.max.append(inf)
            ocp.g = vertcat(ocp.g, mu * normal_contact_force - tangential_contact_force)
            ocp.g_bounds.min.append(0)
            ocp.g_bounds.max.append(inf)

    @staticmethod
    def continuity_constraint(ocp):
        """
        Adds continuity constraints between each nodes and its neighbours. It is possible to add a continuity
        constraint between first and last nodes to have a loop (nlp.is_cyclic_constraint).
        :param ocp: An OptimalControlProgram class.
        """
        # Dynamics must be sound within phases
        for nlp in ocp.nlp:
            # Loop over shooting nodes
            for k in range(nlp["ns"]):
                # Create an evaluation node
                end_node = nlp["dynamics"].call({"x0": nlp["X"][k], "p": nlp["U"][k]})["xf"]

                # Save continuity constraints
                ocp.g = vertcat(ocp.g, end_node - nlp["X"][k + 1])
                for _ in range(nlp["nx"]):
                    ocp.g_bounds.min.append(0)
                    ocp.g_bounds.max.append(0)

        # Dynamics must be continuous between phases
        for i in range(len(ocp.nlp) - 1):
            if ocp.nlp[i]["nx"] != ocp.nlp[i + 1]["nx"]:
                raise RuntimeError("Phase constraints without same nx is not supported yet")

            ocp.g = vertcat(ocp.g, ocp.nlp[i]["X"][-1] - ocp.nlp[i + 1]["X"][0])
            for _ in range(ocp.nlp[i]["nx"]):
                ocp.g_bounds.min.append(0)
                ocp.g_bounds.max.append(0)

        if ocp.is_cyclic_constraint:
            # Save continuity constraints between final integration and first node
            if ocp.nlp[0]["nx"] != ocp.nlp[-1]["nx"]:
                raise RuntimeError("Cyclic constraint without same nx is not supported yet")
            ocp.g = vertcat(ocp.g, ocp.nlp[-1]["X"][-1][1:] - ocp.nlp[0]["X"][0][1:])
            for i in range(ocp.nlp[0]["nx"]):
                ocp.g_bounds.min.append(0)
                ocp.g_bounds.max.append(0)
