"""
Basic functions on surface meshes.
"""

# Author: Oualid Benkarim <oualid.benkarim@mcgill.ca>
# License: BSD 3 clause


import warnings
from itertools import combinations

from scipy.spatial.distance import cdist
from scipy.sparse import csgraph as csg
import numpy as np

from vtk import (vtkDataObject, vtkThreshold, vtkGeometryFilter,
                 vtkAppendPolyData)

from .mesh_creation import build_polydata
from .mesh_elements import get_immediate_adjacency
from .array_operations import get_connected_components
from ..vtk_interface import wrap_vtk, serial_connect, get_output
from ..vtk_interface.pipeline import connect
from ..vtk_interface.decorators import wrap_input
from ..utils.parcellation import relabel_consecutive

ASSOC_CELLS = vtkDataObject.FIELD_ASSOCIATION_CELLS
ASSOC_POINTS = vtkDataObject.FIELD_ASSOCIATION_POINTS


@wrap_input(0)
def _surface_selection(surf, array_name, low=-np.inf, upp=np.inf,
                       use_cell=False, keep=True):
    """Selection of points or cells meeting some thresholding criteria.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    array_name : str or ndarray
        Array used to perform selection.
    low : float or -np.inf
        Lower threshold. Default is -np.inf.
    upp : float or np.inf
        Upper threshold. Default is +np.inf.
    use_cell : bool, optional
        If True, apply selection to cells. Otherwise, use points.
        Default is False.
    keep : bool, optional
        If True, elements within the thresholds (inclusive) are kept.
        Otherwise, are discarded. Default is True.

    Returns
    -------
    surf_selected : BSPolyData
        Surface after thresholding.

    """

    if low > upp:
        raise ValueError('Threshold limits are not valid: {0} -- {1}'.
                         format(low, upp))

    at = 'c' if use_cell else 'p'
    if isinstance(array_name, np.ndarray):
        drop_array = True
        array = array_name
        array_name = surf.append_array(array, at=at)
    else:
        drop_array = False
        array = surf.get_array(name=array_name, at=at, return_name=False)

    if array.ndim > 1:
        raise ValueError('Arrays has more than one dimension.')

    if low == -np.inf:
        low = array.min()
    if upp == np.inf:
        upp = array.max()

    if keep is False:
        raise ValueError("Don't support 'keep=False'.")

    # tf = wrap_vtk(vtkThreshold, invert=not keep)
    tf = wrap_vtk(vtkThreshold)
    tf.ThresholdBetween(low, upp)
    if use_cell:
        tf.SetInputArrayToProcess(0, 0, 0, ASSOC_CELLS, array_name)
    else:
        tf.SetInputArrayToProcess(0, 0, 0, ASSOC_POINTS, array_name)

    gf = wrap_vtk(vtkGeometryFilter(), merging=False)
    surf_sel = serial_connect(surf, tf, gf)

    # Check results
    mask = np.logical_and(array >= low, array <= upp)
    if keep:
        n_expected = np.count_nonzero(mask)
    else:
        n_expected = np.count_nonzero(~mask)

    n_sel = surf_sel.n_cells if use_cell else surf_sel.n_points
    if n_expected != n_sel:
        element = 'cells' if use_cell else 'points'
        warnings.warn('The number of selected {0} is different than expected. '
                      'This may be due to the topology after after selection: '
                      'expected={1}, selected={2}.'.
                      format(element, n_expected, n_sel))

    if drop_array:
        surf.remove_array(name=array_name, at=at)
        surf_sel.remove_array(name=array_name, at=at)

    return surf_sel


@wrap_input(0)
def _surface_mask(surf, mask, use_cell=False):
    """Selection fo points or cells meeting some criteria.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    mask : str or ndarray
        Binary boolean or integer array. Zero or False elements are
        discarded.
    use_cell : bool, optional
        If True, apply selection to cells. Otherwise, use points.
        Default is False.

    Returns
    -------
    surf_masked : BSPolyData
        PolyData after masking.

    """

    if isinstance(mask, np.ndarray):
        if np.issubdtype(mask.dtype, np.bool_):
            mask = mask.astype(np.uint8)
    else:
        mask = surf.get_array(name=mask, at='c' if use_cell else 'p')

    if np.any(np.unique(mask) > 1):
        raise ValueError('Cannot work with non-binary mask.')

    return _surface_selection(surf, mask, low=1, upp=1, use_cell=use_cell,
                              keep=True)


def drop_points(surf, array_name, low=-np.inf, upp=np.inf):
    """Remove surface points whose values fall within the threshold.

    Cells corresponding to these points are also removed.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    array_name : str or 1D ndarray
        Array used to perform selection. If str, it must be an array in
        the PointData attributes of the PolyData.
    low : float or -np.inf
        Lower threshold. Default is -np.inf.
    upp : float or np.inf
        Upper threshold. Default is np.inf.

    Returns
    -------
    surf_selected : vtkPolyData or BSPolyData
        PolyData after thresholding.

    See Also
    --------
    :func:`drop_cells`
    :func:`select_points`
    :func:`mask_points`

    """

    return _surface_selection(surf, array_name, low=low, upp=upp, keep=False)


def drop_cells(surf, array_name, low=-np.inf, upp=np.inf):
    """Remove surface cells whose values fall within the threshold.

    Points corresponding to these cells are also removed.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    array_name : str or 1D ndarray
        Array used to perform selection. If str, it must be an array in
        the CellData attributes of the PolyData.
    low : float or -np.inf
        Lower threshold. Default is -np.inf.
    upp : float or np.inf
        Upper threshold. Default is np.inf.

    Returns
    -------
    surf_selected : vtkPolyData or BSPolyData
        PolyData after thresholding.

    See Also
    --------
    :func:`drop_points`
    :func:`select_cells`
    :func:`mask_cells`

    """

    return _surface_selection(surf, array_name, low=low, upp=upp, use_cell=True,
                              keep=False)


def select_points(surf, array_name, low=-np.inf, upp=np.inf):
    """Select surface points whose values fall within the threshold.

    Cells corresponding to these points are also kept.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    array_name : str or 1D ndarray
        Array used to perform selection. If str, it must be an array in
        the PointData attributes of the PolyData.
    low : float or -np.inf
        Lower threshold. Default is -np.inf.
    upp : float or np.inf
        Upper threshold. Default is np.inf.

    Returns
    -------
    surf_selected : vtkPolyData or BSPolyData
        PolyData after selection.

    See Also
    --------
    :func:`select_cells`
    :func:`drop_points`
    :func:`mask_points`

    """

    return _surface_selection(surf, array_name, low=low, upp=upp, keep=True)


def select_cells(surf, array_name, low=-np.inf, upp=np.inf):
    """Select surface cells whose values fall within the threshold.

    Points corresponding to these cells are also kept.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    array_name : str or 1D ndarray
        Array used to perform selection. If str, it must be an array in
        the CellData attributes of the PolyData.
    low : float or -np.inf
        Lower threshold. Default is -np.inf.
    upp : float or np.inf
        Upper threshold. Default is np.inf.

    Returns
    -------
    surf_selected : vtkPolyData or BSPolyData
        PolyData after selection.

    See Also
    --------
    :func:`select_points`
    :func:`drop_cells`
    :func:`mask_cells`

    """

    return _surface_selection(surf, array_name, low=low, upp=upp, use_cell=True,
                              keep=True)


def mask_points(surf, mask):
    """Mask surface points.

    Cells corresponding to these points are also kept.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    mask : 1D ndarray
        Binary boolean array. Zero elements are discarded.

    Returns
    -------
    surf_masked : vtkPolyData or BSPolyData
        PolyData after masking.

    See Also
    --------
    :func:`mask_cells`
    :func:`drop_points`
    :func:`select_points`

    """

    return _surface_mask(surf, mask)


def mask_cells(surf, mask):
    """Mask surface cells.

    Points corresponding to these cells are also kept.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    mask : 1D ndarray
        Binary boolean array. Zero elements are discarded.

    Returns
    -------
    surf_masked : vtkPolyData or BSPolyData
        PolyData after masking.

    See Also
    --------
    :func:`mask_points`
    :func:`drop_cells`
    :func:`select_cells`

    """

    return _surface_mask(surf, mask, use_cell=True)


def combine_surfaces(*surfs):
    """ Combine surfaces.

    Parameters
    ----------
    surfs : sequence of vtkPolyData and/or BSPolyData
        Input surfaces.

    Returns
    -------
    res : BSPolyData
        Combination of input surfaces.

    See Also
    --------
    :func:`split_surface`

    """

    alg = vtkAppendPolyData()
    for s in surfs:
        alg = connect(s, alg, add_conn=True)
    return get_output(alg)


@wrap_input(0)
def split_surface(surf, labeling=None):
    """ Split surface according to the labeling.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    labeling : str, 1D ndarray or None, optional
        Array used to perform the splitting. If str, it must be an array in
        the PointData attributes of `surf`. If None, split surface in its
        connected components. Default is None.

    Returns
    -------
    res : dict[int, BSPolyData]
        Dictionary of sub-surfaces for each label.

    See Also
    --------
    :func:`combine_surfaces`
    :func:`mask_points`

    """

    if labeling is None:
        labeling = get_connected_components(surf)
    elif isinstance(labeling, str):
        labeling = surf.get_array(labeling, at='p')

    ulab = np.unique(labeling)
    return {l: mask_points(surf, labeling == l) for l in ulab}


@wrap_input(0)
def downsample_with_parcellation(surf, labeling, name='parcel',
                                 check_connected=True):
    """ Downsample surface according to the labeling.

    Such that, each parcel centroid is used as a point in the new donwsampled
    surface. Connectivity is based on neighboring parcels.

    Parameters
    ----------
    surf : vtkPolyData or BSPolyData
        Input surface.
    labeling : str or 1D ndarray
        Array of labels used to perform the downsampling. If str, it must be an
        array in the PointData attributes of `surf`.
    name : str, optional
        Name of the downsampled parcellation appended to the PointData of the
        new surface. Default is 'parcel'.
    check_connected : bool, optional
        Whether to check if the points in each parcel are connected.
        Downsampling may produce inconsistent results if some parcels have more
        than one connected component. Default is True.

    Returns
    -------
    res : BSPolyData
        Downsampled surface.

    """

    if isinstance(labeling, str):
        labeling = surf.get_array(labeling, at='p')

    labeling_small = np.unique(labeling)
    nlabs = labeling_small.size

    labeling_con = relabel_consecutive(labeling)

    adj = get_immediate_adjacency(surf)
    adj_neigh = adj.multiply(labeling_con).tocsr()

    adj_small = np.zeros((nlabs, nlabs), dtype=np.bool)
    for i in range(nlabs):
        arow = adj_neigh[labeling_con == i]
        for j in range(i + 1, nlabs):
            adj_small[j, i] = adj_small[i, j] = np.any(arow.data == j)

    points = np.empty((nlabs, 3))
    cells = []
    for i in range(nlabs):
        m = labeling_con == i

        if check_connected and csg.connected_components(adj[m][:, m])[0] > 1:
            warnings.warn("Parcel %d is not fully connected. Downsampling may "
                          "produce inconsistent results." % labeling_small[i])

        neigh = np.unique(adj_neigh[m].data)
        neigh = neigh[neigh != i]
        if neigh.size < 2:
            continue

        edges = np.array(list(combinations(neigh, 2)))
        edges = edges[adj_small[edges[:, 0], edges[:, 1]]]
        c = np.hstack([np.full(edges.shape[0], i)[:, None], edges])
        cells.append(c)

        p = surf.Points[m]
        d = cdist(p, p.mean(0, keepdims=True))[:, 0]
        points[i] = p[np.argmin(d)]

    cells = np.unique(np.sort(np.vstack(cells), axis=1), axis=0)
    surf_small = build_polydata(points, cells=cells)
    surf_small.append_array(labeling_small, name=name, at='p')
    return surf_small
