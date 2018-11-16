# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import itertools

import bpy
from bpy.props import (BoolProperty, StringProperty, FloatProperty, IntProperty)

from mathutils import Vector

from sverchok.utils.sv_obj_helper import SvObjHelper
from sverchok.utils.sv_bmesh_utils import bmesh_from_pydata
from sverchok.utils.sv_viewer_utils import matrix_sanitizer
from sverchok.node_tree import SverchCustomTreeNode
from sverchok.data_structure import (dataCorrect, fullList, updateNode)


def tuple_to_enumdata(*iterable):
    return [(k, k, '', i) for i, k in enumerate(iterable)]

dimension_modes = tuple_to_enumdata("3D", "2D")
fill_modes_2d = tuple_to_enumdata('NONE', 'BACK', 'FRONT', 'BOTH')
fill_modes_3d = tuple_to_enumdata('HALF', 'FRONT', 'BACK', 'FULL')
mode_options = tuple_to_enumdata("Merge", "Duplicate", "Unique")

def set_curve_props(node, cu):
    cu.bevel_depth = node.depth
    cu.bevel_resolution = node.resolution
    cu.dimensions = node.curve_dimensions
    cu.fill_mode = node.set_fill_mode()


# -- DUPLICATES --
def make_duplicates_live_curve(node, object_index, verts, edges, matrices):
    curves = bpy.data.curves
    objects = bpy.data.objects
    scene = bpy.context.collection

    # if curve data exists, pick it up else make new curve
    # this curve is then used as a data.curve for all objects generated by this node..
    # objects still have slow creation time, but storage is very good due to
    # reuse of curve data and applying matrices to objects instead.

    # only make the curve data.
    curve_name = node.basedata_name + '.cloner.' + str("%04d" % obj_index)
    cu = curves.get(curve_name)
    if not cu:
        cu = curves.new(name=curve_name, type='CURVE')

    # wipe!
    if cu.splines:
        cu.splines.clear()

    set_curve_props(node, cu)
    
    # rebuild!
    for edge in edges:
        v0, v1 = verts[edge[0]], verts[edge[1]]
        full_flat = [v0[0], v0[1], v0[2], 0.0, v1[0], v1[1], v1[2], 0.0]

        # each spline has a default first coordinate but we need two.
        segment = cu.splines.new('POLY')
        segment.points.add(1)
        segment.points.foreach_set('co', full_flat)

    # if object reference exists, pick it up else make a new one
    # assign the same curve to all Objects.
    for obj_index, matrix in enumerate(matrices):
        m = matrix_sanitizer(matrix)

        # get object to clone the Curve data into.
        obj_name = node.basedata_name + '.' + str("%04d" % obj_index)

        obj = objects.get(obj_name)
        if not obj:
            obj = objects.new(obj_name, cu)
            scene.objects.link(obj)

        # make sure this object is known by its origin
        obj['basedata_name'] = node.basedata_name
        obj['madeby'] = node.name
        obj['idx'] = obj_index
        obj.matrix_local = m


# -- MERGE --
def make_merged_live_curve(node, obj_index, verts, edges, matrices):

    obj, cu = node.get_obj_curve(obj_index)
    set_curve_props(node, cu)
    
    for matrix in matrices:
        m = matrix_sanitizer(matrix)

        # and rebuild
        for edge in edges:
            v0, v1 = m @ Vector(verts[edge[0]]), m @ Vector(verts[edge[1]])

            full_flat = [v0[0], v0[1], v0[2], 0.0, v1[0], v1[1], v1[2], 0.0]

            # each spline has a default first coordinate but we need two.
            segment = cu.splines.new('POLY')
            segment.points.add(1)
            segment.points.foreach_set('co', full_flat)


# -- UNIQUE --
def live_curve(obj_index, verts, edges, matrix, node):

    obj, cu = node.get_obj_curve(obj_index)
    set_curve_props(node, cu)

    # and rebuild

    if node.curve_dimensions == '3D':

        for edge in edges:
            v0, v1 = verts[edge[0]], verts[edge[1]]
            full_flat = [v0[0], v0[1], v0[2], 0.0, v1[0], v1[1], v1[2], 0.0]

            # each spline has a default first coordinate but we need two.
            segment = cu.splines.new('POLY')
            segment.points.add(1)
            segment.points.foreach_set('co', full_flat)
    else:

        for v_obj, e_obj in zip(verts, edges):
            segment = cu.splines.new('POLY')
            #v1, v2, v3 = v_obj[e_obj[0][0]]
            #points = [v1, v2, v3, 0.0]
            points = []
            prev = []
            if len(v_obj) == len(e_obj):
                e_obj.pop(-1)
            e_obj.sort()
            segment.points.add(len(e_obj))
            for edge in e_obj:
                for e in edge:
                    if e not in prev:
                        prev.append(e)
                        v1 = v_obj[e]
                        points.extend([v1[0], v1[1], v1[2], 0.0])
            segment.points.foreach_set('co', points)
            segment.use_cyclic_u = True        

    return obj


def make_curve_geometry(node, context, obj_index, verts, *topology):
    edges, matrix = topology
    
    sv_object = live_curve(obj_index, verts, edges, matrix, node)
    sv_object.hide_select = False
    node.push_custom_matrix_if_present(sv_object, matrix)


class SvCurveViewerNodeV28(bpy.types.Node, SverchCustomTreeNode, SvObjHelper):
    """
    Triggers: CV object curves
    Tooltip: Advanced 2d/3d curve outputting into scene
    """

    bl_idname = 'SvCurveViewerNodeV28'
    bl_label = 'Curve Viewer'
    bl_icon = 'MOD_CURVE'

    selected_mode: bpy.props.EnumProperty(
        items=mode_options,
        description="merge or use duplicates",
        default="Unique",
        update=updateNode)
    
    curve_dimensions: bpy.props.EnumProperty(
        items=dimension_modes, update=updateNode,
        description="2D or 3D curves", default="3D")

    fill_2D: bpy.props.EnumProperty(
        items=fill_modes_2d, description="offers fill more for 2d Curve data",
        default=fill_modes_2d[2][0], update=updateNode)

    fill_3D: bpy.props.EnumProperty(
        items=fill_modes_3d, description="offers fill more for 3d Curve data",
        default=fill_modes_3d[3][0], update=updateNode)

    data_kind: StringProperty(default='CURVE')
    grouping: BoolProperty(default=False)

    depth: FloatProperty(min=0.0, default=0.2, update=updateNode)
    resolution: IntProperty(min=0, default=3, update=updateNode)

    def sv_init(self, context):
        self.sv_init_helper_basedata_name()
        self.inputs.new('VerticesSocket', 'vertices')
        self.inputs.new('StringsSocket', 'edges')
        self.inputs.new('MatrixSocket', 'matrix')

    def draw_buttons(self, context, layout):

        self.draw_live_and_outliner(context, layout)

        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(self, "grouping", text="Group", toggle=True)
        row.separator()
        row.prop(self, "selected_mode", expand=True)

        self.draw_object_buttons(context, layout)

        layout.row().prop(self, 'curve_dimensions', expand=True)
        col = layout.column(align=True)
        col.prop(self, 'depth', text='depth radius')
        col.prop(self, 'resolution', text='surface resolution')
        
        col.separator()
        row = col.row()
        row.prop(self, 'fill_' + self.curve_dimensions, expand=True)

    def draw_buttons_ext(self, context, layout):
        self.draw_buttons(context, layout)
        self.draw_ext_object_buttons(context, layout)

    def set_fill_mode(self):
        return getattr(self, "fill_" + self.curve_dimensions) 

    def remove_cloner_curve(self, obj_index):
        # opportunity to remove the .cloner.
        if self.selected_mode == 'Duplicate':
            curve_name = self.basedata_name + '.cloner.' + str("%04d" % obj_index)
            cu = bpy.data.curves.get(curve_name)
            if cu:
                bpy.data.curves.remove(cu) 

    def output_dupe_or_merged_geometry(self, TYPE, mverts, *mrest):
        '''
        this should probably be shared in the main process function but
        for prototyping convenience and logistics i will keep this separate
        for the time-being. Upon further consideration, i might suggest keeping this
        entirely separate to keep function length shorter.
        '''
        verts = mverts[0]
        edges = mrest[0][0]
        matrices = mrest[1]

        # object index = 0 because these modes will output only one object.
        if TYPE == 'Merge':
            make_merged_live_curve(self, 0, verts, edges, matrices)
        elif TYPE == 'Duplicate':
            make_duplicates_live_curve(self, 0, verts, edges, matrices)

    def get_geometry_from_sockets(self):

        def get(socket_name):
            data = self.inputs[socket_name].sv_get(default=[])
            return dataCorrect(data)

        mverts = get('vertices')
        medges = get('edges')
        mmtrix = get('matrix')
        return mverts, medges, mmtrix

    def get_structure(self, stype, sindex):
        if not stype:
            return []

        try:
            j = stype[sindex]
        except IndexError:
            j = []
        finally:
            return j

    def process(self):

        if not self.activate:
            return

        if not (self.inputs['vertices'].is_linked and self.inputs['edges'].is_linked):
            # possible remove any potential existing geometry here too
            return

        # maybe if edges is not linked that the vertices can be assumed to be
        # sequential and auto generated.. maybe... maybe.

        mverts, *mrest = self.get_geometry_from_sockets()

        mode = self.selected_mode
        single_set = (len(mverts) == 1) and (len(mrest[-1]) > 1)
        has_matrices = self.inputs['matrix'].is_linked

        if single_set and (mode in {'Merge', 'Duplicate'}) and has_matrices:
            obj_index = 0
            self.output_dupe_or_merged_geometry(mode, mverts, *mrest)

            if mode == "Duplicate":
                obj_index = len(mrest[1]) - 1

        else:

            def get_edges_matrices(obj_index):
                for geom in mrest:
                    yield self.get_structure(geom, obj_index)

            # extend all non empty lists to longest of mverts or *mrest
            maxlen = max(len(mverts), *(map(len, mrest)))
            fullList(mverts, maxlen)
            for idx in range(2):
                if mrest[idx]:
                    fullList(mrest[idx], maxlen)

            if self.curve_dimensions == '3D':

                for obj_index, Verts in enumerate(mverts):
                    if not Verts:
                        continue

                    data = get_edges_matrices(obj_index)
                    make_curve_geometry(self, bpy.context, obj_index, Verts, *data)

                # we must be explicit
                obj_index = len(mverts) - 1

            else:
                obj_index = 0
                make_curve_geometry(self, bpy.context, obj_index, mverts, *mrest)



        self.remove_non_updated_objects(obj_index)
        objs = self.get_children()

        if self.grouping:
            self.to_group(objs)

        self.set_corresponding_materials()
        self.remove_cloner_curve(obj_index)


def register():
    bpy.utils.register_class(SvCurveViewerNodeV28)


def unregister():
    bpy.utils.unregister_class(SvCurveViewerNodeV28)
