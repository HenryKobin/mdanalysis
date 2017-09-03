# -*- Mode: python; tab-width: 4; indent-tabs-mode:nil; coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
#
# MDAnalysis --- http://www.mdanalysis.org
# Copyright (c) 2006-2017 The MDAnalysis Development Team and contributors
# (see the file AUTHORS for the full list of names)
#
# Released under the GNU Public Licence, v2 or any higher version
#
# Please cite your use of MDAnalysis in published work:
#
# R. J. Gowers, M. Linke, J. Barnoud, T. J. E. Reddy, M. N. Melo, S. L. Seyler,
# D. L. Dotson, J. Domanski, S. Buchoux, I. M. Kenney, and O. Beckstein.
# MDAnalysis: A Python package for the rapid analysis of molecular dynamics
# simulations. In S. Benthall and S. Rostrup editors, Proceedings of the 15th
# Python in Science Conference, pages 102-109, Austin, TX, 2016. SciPy.
#
# N. Michaud-Agrawal, E. J. Denning, T. B. Woolf, and O. Beckstein.
# MDAnalysis: A Toolkit for the Analysis of Molecular Dynamics Simulations.
# J. Comput. Chem. 32 (2011), 2319--2327, doi:10.1002/jcc.21787
#

"""
Periodic KDTree --- :mod:`MDAnalysis.lib.pkdtree`
===============================================================================

This module contains class to allow searches on a KDTree involving periodic
boundary conditions.
"""

from __future__ import absolute_import

import numpy as np
from Bio.KDTree import _CKDTree

__all__ = ['PeriodicKDTree', ]


class PeriodicKDTree(object):
    """
    Wrapper around Bio.KDTree._CKDTree to enable search with periodic boundary conditions.
    
    A tree is first constructed with the coordinates wrapped onto the central cell.
    
    A query for neighbors around a center point is performed first by wrapping the center
    point coordinates to the central cell, then generating images of this wrapped
    center point and also searching for neighbors around the images.
    
    Only the necessary number of center point images is generated for each case. For
    instance, if the wrapped center point lies well within the cell and far away
    from the cell boundaries, there may be no need to generate any center point image.
    """

    def __init__(self, box, bucket_size=10):
        """
        Parameters
        ----------
        box : array-like or ``None``, optional, default ``None``
          Simulation cell dimensions in the form of
          :attr:`MDAnalysis.trajectory.base.Timestep.dimensions` when
          periodic boundary conditions should be taken into account for
          the calculation of contacts.
        bucket_size : int
          Number of entries in leafs of the KDTree. If you suffer poor
          performance you can play around with this number. Increasing the
          `bucket_size` will speed up the construction of the KDTree but
          slow down the search.
        """
        self.dim = 3  # Strict implementation for 3D
        self.kdt = _CKDTree.KDTree(self.dim, bucket_size)
        self.built = 0
        if len(box) != self.dim:
            raise Exception('Expected array of length {}'.format(self.dim))
        self.box = np.copy(np.asarray(box))
        # zero is the flag for no periodic boundary conditions
        self.box = np.where(self.box == np.inf, 0.0, self.box)
        self.box = np.where(self.box > 0.0, self.box, 0.0)
        if not self.box.any():
            raise Exception('No periodic axis found')
        self._indices = list()

    def set_coords(self, coords):
        """
        Add coordinates of the points. Wrapping of coordinates to the central
        cell is enforced along the periodic axes.

        Parameters
        ----------
        coords: NumPy.array
          Positions of points, shape=(N, 3) for N atoms.
        """
        if coords.min() <= -1e6 or coords.max() >= 1e6:
            # Same exception class as in Bio.KDTree.KDTree.set_coords
            raise Exception('Points should lie between -1e6 and 1e6')
        if len(coords.shape) != 2 or coords.shape[1] != self.dim:
            raise Exception('Expected a (N, {}) NumPy array'.format(self.dim))
        wrapped_data = (coords - np.where(self.box > 0.0,
                                          np.floor(coords / self.box) * self.box, 0.0))
        self.kdt.set_data(wrapped_data)
        self.built = 1

    def find_centers(self, center, radius):
        """
        Find relevant images of a center point.
        
        Parameters
        ----------
        center: NumPy.array
          Coordinates of the query center point
        radius: float 
          Maximum distance from center in search for neighbors

        Returns
        ------
        :class:`List`
          center point and its relevant images
        """
        wrapped_center = (center - np.where(self.box > 0.0,
                                            np.floor(center / self.box) * self.box, 0.0))
        centers = [wrapped_center, ]
        extents = self.box/2.0
        extents = np.where(extents > radius, radius, extents)
        # displacements are vectors that we add to wrapped_center to generate images
        # "up" or "down" the central cell along the axis that we happen to be looking.
        displacements = list()
        for i in range(self.dim):
            displacement = np.zeros(self.dim)
            extent = extents[i]
            if extent > 0.0:
                if self.box[i] - wrapped_center[i] < extent:
                    displacement[i] = -self.box[i]  # displacement generates "lower" image
                    displacements.append(displacement)
                elif wrapped_center[i] < extent:
                    displacement[i] = self.box[i]  # displacement generates "upper" image
                    displacements.append(displacement)
        # If we have displacements along more than one axis, we have
        # to combine them. This happens when wrapped_center is close
        # to any edge or vertex of the central cell.
        # face, n_displacements==1; no combination
        # edge, n_displacements==2; combinations produce one extra displacement
        # vertex, n_displacements==3; combinations produce five extra displacements
        n_displacements = len(displacements)
        if n_displacements > 1:
            for start in range(n_displacements - 1, -1, -1):
                for i in range(start+1, len(displacements)):
                    displacements.append(displacements[start]+displacements[i])
        centers.extend([wrapped_center + d for d in displacements])
        return centers

    def search(self, center, radius):
        """Search all points within radius of center and its periodic images.
        Wrapping of center coordinates is enforced to enable comparison to
        wrapped coordinates of points in the tree.

        Parameter
        ---------
        center: NumPy.array
          origin around which to search for neighbors
        radius: float
          maximum distance around which to search for neighbors. The search radius
          is set to half the smallest periodicity if radius exceeds this value.
        """
        if not self.built:
            raise Exception('No point set specified')
        if center.shape != (self.dim,):
            raise Exception('Expected a ({},) NumPy array'.format(self.dim))
        self._indices = None  # clear previous search
        # Search neighbors for all relevant images of center point
        for c in self.find_centers(center, radius):
            self.kdt.search_center_radius(c, radius)
            if self._indices is None:
                self._indices = self.kdt.get_indices()
            else:
                np.append(self._indices, np.arange(2))
        if self._indices is not None:  # sort and remove duplicates
            self._indices = np.sort(np.unique(self._indices))

    def get_indices(self):
        return self._indices


if __name__ == "__main__" :
    box = np.array([10, 10, 10], dtype=np.float32)
    coords = np.array([[2, 2, 2],
                       [5, 5, 5],
                       [1.1, 1.1, 1.1],
                       [11, -11, 11],  # wrapped to [1, 9, 1]
                       [21, 21, 3]],  # wrapped to [1, 1, 3]
                      dtype=np.float32)
    tree = PeriodicKDTree(box)
    tree.set_coords(coords)

    center = np.array([11, 2, 2], dtype=np.float32)
    wrapped_center = center - np.where(tree.box > 0.0, np.floor(center / tree.box) * tree.box, 0.0)
    tree.search(center, 1.5)
    for i in tree.get_indices():
        neighbor = coords[i]
        wrapped_neighbor = (neighbor - np.where(tree.box > 0.0, np.floor(neighbor / tree.box) * tree.box, 0.0))
        distance = np.sqrt(np.sum((wrapped_center-wrapped_neighbor)**2))

    center = np.array([21, -31, 1], dtype=np.float32)
    wrapped_center = center - np.where(tree.box > 0.0, np.floor(center / tree.box) * tree.box, 0.0)
    tree.search(center, 1.5)
    for i in tree.get_indices():
        neighbor = coords[i]
        wrapped_neighbor = (neighbor - np.where(tree.box > 0.0, np.floor(neighbor / tree.box) * tree.box, 0.0))
        distance = np.sqrt(np.sum((wrapped_center-wrapped_neighbor)**2))

    print('hello')