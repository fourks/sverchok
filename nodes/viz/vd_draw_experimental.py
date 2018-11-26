# This file is part of project Sverchok. It's copyrighted by the contributors
# recorded in the version control history of the file, available from
# its original location https://github.com/nortikin/sverchok/commit/master
#  
# SPDX-License-Identifier: GPL3
# License-Filename: LICENSE

from math import pi

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from bpy.props import (
    StringProperty, BoolProperty, FloatVectorProperty, EnumProperty)

# import mathutils
from mathutils import Vector, Matrix
from mathutils.geometry import tessellate_polygon as tessellate

import sverchok
from sverchok.node_tree import SverchCustomTreeNode
from sverchok.data_structure import node_id, updateNode, enum_item_4, enum_item_5
from sverchok.ui.bgl_callback_3dview import callback_disable, callback_enable
from sverchok.utils.sv_batch_primitives import MatrixDraw28
from sverchok.utils.sv_bmesh_utils import bmesh_from_pydata
from sverchok.utils.geom import multiply_vectors_deep
from sverchok.utils.modules.geom_utils import obtain_normal3 as normal 

def edges_from_faces(indices):
    """ we don't want repeat edges, ever.."""
    out = set()
    concat = out.add
    for face in indices:
        for edge in zip(face, list(face[1:]) + list([face[0]])):
            concat(tuple(sorted(edge)))
    return list(out)

def ensure_triangles(coords, indices):
    """ 
    this fully tesselates the incoming topology into tris,
    not optimized for meshes that don't contain ngons 
    """
    new_indices = []
    concat = new_indices.append
    concat2 = new_indices.extend
    for idxset in indices:
        num_verts = len(idxset)
        if num_verts == 3:
            concat(tuple(idxset))
        elif num_verts == 4:
            # a b c d  ->  [a, b, c], [a, c, d]
            concat2([(idxset[0], idxset[1], idxset[2]), (idxset[0], idxset[2], idxset[3])])
        else:
            subcoords = [Vector(coords[idx]) for idx in idxset]
            for pol in tessellate([subcoords]):
                concat([idxset[i] for i in pol])
    return new_indices

def generate_facet_data(verts, faces, face_color, vector_light):
    out_verts = []
    out_vcols = []
    concat_verts = out_verts.extend
    concat_vcols = out_vcols.extend
    for face in faces:
        vecs = [verts[j] for j in face]
        concat_verts(vecs)

        normal_no = Vector(normal(*vecs))
        normal_no = (normal_no.angle(vector_light, 0)) / pi

        r = (normal_no * face_color[0]) - 0.1
        g = (normal_no * face_color[1]) - 0.1
        b = (normal_no * face_color[2]) - 0.1
        vcol = (r+0.2, g+0.2, b+0.2, 1.0)
        concat_vcols([vcol, vcol, vcol])

    return out_verts, out_vcols

def generate_smooth_data(verts, faces, face_color, vector_light):
    """ this piggy backs off bmesh's automated normal calculation... """
    out_vcols = []
    concat_vcols = out_vcols.append

    bm = bmesh_from_pydata(verts, [], faces, normal_update=True)

    for vert in bm.verts:
        normal_no = (vert.normal.angle(vector_light, 0)) / pi
        r = (normal_no * face_color[0]) - 0.1
        g = (normal_no * face_color[1]) - 0.1
        b = (normal_no * face_color[2]) - 0.1
        vcol = (r+0.2, g+0.2, b+0.2, 1.0)
        concat_vcols(vcol)

    return out_vcols


def draw_matrix(context, args):
    """ this takes one or more matrices packed into an iterable """
    mdraw = MatrixDraw28()
    for matrix in args[0]:
        mdraw.draw_matrix(matrix)


def draw_uniform(GL_KIND, coords, indices, color):
    shader = gpu.shader.from_builtin('3D_UNIFORM_COLOR')
    if indices:
        batch = batch_for_shader(shader, GL_KIND, {"pos" : coords}, indices=indices)
    else:
        batch = batch_for_shader(shader, GL_KIND, {"pos" : coords})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)

def draw_smooth(coords, vcols, indices=None):
    shader = gpu.shader.from_builtin('3D_SMOOTH_COLOR')
    if indices:
        print(len(coords), len(vcols))
        batch = batch_for_shader(shader, 'TRIS', {"pos" : coords, "color": vcols}, indices=indices)
    else:
        batch = batch_for_shader(shader, 'TRIS', {"pos" : coords, "color": vcols})
    batch.draw(shader)


def draw_verts(context, args):
    geom, config = args
    draw_uniform('POINTS', geom.verts, None, config.vcol)

def draw_edges(context, args):
    geom, config = args
    coords, indices = geom.verts, geom.edges
    draw_uniform('LINES', coords, indices, config.line4f)
    if config.display_verts:
        draw_uniform('POINTS', geom.verts, None, config.vcol)

def draw_faces(context, args):
    geom, config = args

    if config.display_faces:
        if config.shade == "flat":
            draw_uniform('TRIS', geom.verts, geom.faces, config.face4f)
        elif config.shade == "facet":
            draw_smooth(geom.facet_verts, geom.facet_verts_vcols)
        elif config.shade == "smooth":
            draw_smooth(geom.verts, geom.smooth_vcols, indices=geom.faces)
            pass

    if config.display_edges:
        draw_uniform('LINES', geom.verts, geom.edges, config.line4f)
    if config.display_verts:
        draw_uniform('POINTS', geom.verts, None, config.vcol)

class SvVDExperimental(bpy.types.Node, SverchCustomTreeNode):
    """
    Triggers: exp vd
    Tooltip: experimental drawing node
    
    not a very exciting node.
    """

    bl_idname = 'SvVDExperimental'
    bl_label = 'VD Experimental'
    bl_icon = 'GREASEPENCIL'

    n_id: StringProperty(default='')
    activate: BoolProperty(name='Show', description='Activate', default=True, update=updateNode)

    vert_color: FloatVectorProperty(
        subtype='COLOR', min=0, max=1, default=(0.8, 0.8, 0.8, 1.0),
        name='vert color', size=4, update=updateNode)

    edge_color: FloatVectorProperty(
        subtype='COLOR', min=0, max=1, default=(0.03, 0.24, 0.42, 1.0),
        name='edge color', size=4, update=updateNode)

    face_color: FloatVectorProperty(
        subtype='COLOR', min=0, max=1, default=(0.14, 0.54, 0.81, 1.0),
        name='face color', size=4, update=updateNode)

    vector_light: FloatVectorProperty(
        name='vector light', subtype='DIRECTION', min=0, max=1, size=3,
        default=(0.2, 0.6, 0.4), update=updateNode)    

    display_verts: BoolProperty(default=False, update=updateNode, name="display verts")
    display_edges: BoolProperty(default=True, update=updateNode, name="display edges")
    display_faces: BoolProperty(default=True, update=updateNode, name="display faces")

    selected_draw_mode: EnumProperty(
        items=enum_item_5(["flat", "facet", "smooth"], ['SNAP_VOLUME', 'ALIASED', 'ANTIALIASED']), 
        description="pick how the node will draw faces",
        default="flat", update=updateNode
    )

    def sv_init(self, context):
        inew = self.inputs.new
        inew('VerticesSocket', 'verts')
        inew('StringsSocket', 'edges')
        inew('StringsSocket', 'faces')
        inew('MatrixSocket', 'matrix')

    def draw_buttons(self, context, layout):
        r0 = layout.row()
        r0.prop(self, "activate", text="", icon="RESTRICT_RENDER_" + ("OFF" if self.activate else "ON"))
        r0.separator()
        r0.prop(self, "selected_draw_mode", expand=True, text='')
        
        b1 = layout.column()
        if b1:
            inside_box = b1.row(align=True)
            button_column = inside_box.column(align=True)
            button_column.prop(self, "display_verts", text='', icon="UV_VERTEXSEL")
            button_column.prop(self, "display_edges", text='', icon="UV_EDGESEL")
            button_column.prop(self, "display_faces", text='', icon="UV_FACESEL")

            colors_column = inside_box.column(align=True)
            colors_column.prop(self, "vert_color", text='')
            colors_column.prop(self, "edge_color", text='')
            colors_column.prop(self, "face_color", text='')

    def draw_buttons_ext(self, context, layout):
        layout.prop(self, 'vector_light', text='')

    def process(self):
        if not (self.id_data.sv_show and self.activate):
            callback_disable(node_id(self))
            return

        n_id = node_id(self)
        callback_disable(n_id)

        verts_socket, edges_socket, faces_socket, matrix_socket = self.inputs[:4]

        if verts_socket.is_linked: 
            geom = lambda: None
            config = lambda: None

            config.vector_light = self.vector_light[:]
            config.vcol = self.vert_color[:]
            config.line4f = self.edge_color[:]
            config.face4f = self.face_color[:]
            config.display_verts = self.display_verts
            config.display_edges = self.display_edges
            config.display_faces = self.display_faces
            config.shade = self.selected_draw_mode
            
            edge_indices = None
            face_indices = None
            
            propv = verts_socket.sv_get(deepcopy=False, default=[])
            coords = propv[0]

            if edges_socket.is_linked:
                prope = edges_socket.sv_get(deepcopy=False, default=[])
                edge_indices = prope[0]
            
            if faces_socket.is_linked:
                propf = faces_socket.sv_get(deepcopy=False, default=[])
                face_indices = propf[0]

            if matrix_socket.is_linked:
                # for now just deal with first
                m = matrix_socket.sv_get(deepcopy=False, default=[Matrix()])[0]
                coords = multiply_vectors_deep(m, coords)
      
            geom.verts = coords

            if self.display_verts and not any([self.display_edges, self.display_faces]):
                draw_data = {
                    'tree_name': self.id_data.name[:],
                    'custom_function': draw_verts,
                    'args': (geom, config)
                } 
                callback_enable(n_id, draw_data)
                return

            if edges_socket.is_linked and not faces_socket.is_linked:
                geom.edges = edge_indices
                draw_data = {
                    'tree_name': self.id_data.name[:],
                    'custom_function': draw_edges,
                    'args': (geom, config)
                } 
                callback_enable(n_id, draw_data)
                return

            if faces_socket.is_linked:

                # we could offer different optimizations, like 
                #  -expecting only tris as input, then no processing
                #  -expecting only quads, then minimal processing needed
                #  -expecting mixed bag, then ensure_triangles (current default)
                if self.display_faces:
                    geom.faces = ensure_triangles(coords, face_indices)

                if self.display_edges:
                    # we don't want to draw the inner edges of triangulated faces; use original face_indices.
                    # pass edges from socket if we can, else we manually compute them from faces
                    geom.edges = edge_indices if edges_socket.is_linked else edges_from_faces(face_indices)

                if self.selected_draw_mode == 'facet' and self.display_faces:
                    facet_verts, facet_verts_vcols = generate_facet_data(geom.verts, geom.faces, config.face4f, config.vector_light)
                    geom.facet_verts = facet_verts
                    geom.facet_verts_vcols = facet_verts_vcols
                elif self.selected_draw_mode == 'smooth' and self.display_faces:
                    geom.smooth_vcols = generate_smooth_data(geom.verts, geom.faces, config.face4f, config.vector_light)

                draw_data = {
                    'tree_name': self.id_data.name[:],
                    'custom_function': draw_faces,
                    'args': (geom, config)
                } 
                callback_enable(n_id, draw_data)
                return

            else:
                # draw verts only
                pass

            return

        elif matrix_socket.is_linked:
            matrices = matrix_socket.sv_get(deepcopy=False, default=[Matrix()])

            draw_data = {
                'tree_name': self.id_data.name[:],
                'custom_function': draw_matrix,
                'args': (matrices,)
            }            

            callback_enable(n_id, draw_data)

    def copy(self, node):
        self.n_id = ''

    @property
    def fully_enabled(self):
        return "matrix" in self.inputs

    def update(self):
        if not self.fully_enabled:
            return

        try:
            socket_one_has_upstream_links = self.inputs[0].other
            socket_two_has_upstream_links = self.inputs[1].other
            
            if not socket_one_has_upstream_links:
                callback_disable(node_id(self))
        except:
            print('vd basic lines update holdout', self.n_id)


def register():
    bpy.utils.register_class(SvVDExperimental)


def unregister():
    bpy.utils.unregister_class(SvVDExperimental)
