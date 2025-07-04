import clr
clr.AddReference('ProtoGeometry')
clr.AddReference('RevitServices')
clr.AddReference('RevitNodes')
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.DesignScript.Geometry import Point as DSPoint, Line as DSLine
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager
from Autodesk.Revit.DB import *

import xml.etree.ElementTree as ET
import math
import System
import re
from System.Collections.Generic import List
import datetime

###############################################################
# Função para converter metros para pés
###############################################################
def meters_to_feet(meters):
    return meters * 3.28084

###############################################################
# Função para ler o arquivo XML
###############################################################
def parse_xml(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()
    return root

###############################################################
# Função para multiplicar dois quaternions
###############################################################
'''def quaternion_multiply(q1, q2):
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    w = w1*w2 - x1*x2 - y1*y2 - z1*z2
    x = w1*x2 + x1*w2 + y1*z2 - z1*y2
    y = w1*y2 - x1*z2 + y1*w2 + z1*x2
    z = w1*z2 + x1*y2 - y1*x2 + z1*w2
    return (w, x, y, z)

###############################################################
# Função para calcular o conjugado de um quaternion
###############################################################
def quaternion_conjugate(q):
    w, x, y, z = q
    return (w, -x, -y, -z)

###############################################################
# Função para aplicar rotação de um ponto usando quaternion
###############################################################
def apply_quaternion_rotation(point, origin, q):
    # Converter o ponto para quaternion com w = 0
    p = (0, point.X - origin.X, point.Y - origin.Y, point.Z - origin.Z)
    
    # Calcular a rotação: Q * p * Q^-1
    q_conj = quaternion_conjugate(q)
    q_p = quaternion_multiply(q, p)
    rotated_p = quaternion_multiply(q_p, q_conj)
    
    # Converter de volta para coordenadas
    new_x = rotated_p[1] + origin.X
    new_y = rotated_p[2] + origin.Y
    new_z = rotated_p[3] + origin.Z
    
    return DSPoint.ByCoordinates(new_x, new_y, new_z)'''

###############################################################
# Função para transformar um ponto do sistema XML para o sistema Dynamo
###############################################################
def transform_point(point):
    x_new = point.X
    y_new = -point.Z  # correção eficaz para o posicionamento
    z_new = point.Y
    return DSPoint.ByCoordinates(x_new, y_new, z_new)

###############################################################
# Função para transformar um quaternion do sistema XML para o sistema Dynamo
###############################################################
def transform_quaternion(q):
    w, x, y, z = q
    # Trocar Y por Z
    return (w, x, z, y)

###############################################################
# Função para criar a linha base e aplicar a transformação
###############################################################
def create_and_transform_line(original_start_point, length, rotation_quat):
    # Criar ponto final no sistema de coordenadas original
    end_point = DSPoint.ByCoordinates(original_start_point.X + length, original_start_point.Y, original_start_point.Z)
    
    # Aplicar rotação ao ponto final em torno do ponto inicial
    if rotation_quat is not None:
        end_point = apply_quaternion_rotation(end_point, original_start_point, rotation_quat)
    
    # Aplicar a transformação aos pontos
    transformed_start_point = transform_point(original_start_point)
    transformed_end_point = transform_point(end_point)
    
    return [transformed_start_point, transformed_end_point]

###############################################################
# Ativar FamilySymbol, se não estiver ativo
###############################################################
def activate_family_symbol(family_symbol):
    if not family_symbol.IsActive:
        family_symbol.Activate()
        DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument.Document.Regenerate()

###############################################################
# Criação das paredes no Revit
###############################################################
def create_walls_in_revit(doc, lines, level, heights, wall_family_name, created_element_ids):
    TransactionManager.Instance.EnsureInTransaction(doc)
    walls = []
    for line, height in zip(lines, heights):
        start_point = line.StartPoint
        end_point = line.EndPoint
        revit_line = Line.CreateBound(
            XYZ(start_point.X, start_point.Y, start_point.Z),
            XYZ(end_point.X, end_point.Y, end_point.Z)
        )
        wall = Wall.Create(
            doc,
            revit_line,
            wall_family_name.Id,
            level.Id,
            height,
            0.0,
            False,
            False
        )
        walls.append(wall)
        created_element_ids.Add(wall.Id)
    TransactionManager.Instance.TransactionTaskDone()
    return walls
###############################################################
# Auxiliares para rotação de pontos
###############################################################

def quaternion_multiply(q1, q2):
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    w = w1*w2 - x1*x2 - y1*y2 - z1*z2
    x = w1*x2 + x1*w2 + y1*z2 - z1*y2
    y = w1*y2 - x1*z2 + y1*w2 + z1*x2
    z = w1*z2 + x1*y2 - y1*x2 + z1*w2
    return (w, x, y, z)

def quaternion_conjugate(q):
    w, x, y, z = q
    return (w, -x, -y, -z)

def apply_quaternion_rotation(point, pivot, q):
    """
    Rotaciona 'point' ao redor de 'pivot' usando o quaternion 'q'.
    point e pivot são XYZ do Revit ou DSPoint convertidos.
    Retorna o ponto rotacionado (XYZ).
    """
    # Converter para quaternion com w = 0, relativo ao pivot
    px = point.X - pivot.X
    py = point.Y - pivot.Y
    pz = point.Z - pivot.Z
    p = (0, px, py, pz)
    
    q_conj = quaternion_conjugate(q)
    # Rotação: q * p * q^-1
    q_p = quaternion_multiply(q, p)
    rotated_p = quaternion_multiply(q_p, q_conj)
    
    # Volta para coordenadas globais
    rx = rotated_p[1] + pivot.X
    ry = rotated_p[2] + pivot.Y
    rz = rotated_p[3] + pivot.Z
    return XYZ(rx, ry, rz)

def quaternion_from_angle_z(angle):
    half = angle / 2.0
    return (math.cos(half), 0.0, 0.0, math.sin(half))


###############################################################
# Criação de portas e janelas no Revit
###############################################################
def create_openings_in_revit(doc, walls, wall_data, door_family_symbol, window_family_symbol, alley_family_symbol, created_element_ids, level):
    """
    Cria portas e janelas (structure_type = 'Door' ou 'Window') em cada parede,
    aplicando o mesmo método de rotação a ambas via quaternions.
    """
    # Ativa símbolos se necessário
    def activate_family_symbol(fam_symbol):
        if not fam_symbol.IsActive:
            fam_symbol.Activate()
            doc.Regenerate()

    activate_family_symbol(door_family_symbol)
    activate_family_symbol(window_family_symbol)
    activate_family_symbol(alley_family_symbol)
    TransactionManager.Instance.EnsureInTransaction(doc)

    level_elevation = level.Elevation  # Elevação do nível selecionado

    for wall, data in zip(walls, wall_data):
        # 1) Obter origem e direção da parede
        wall_curve = wall.Location.Curve
        wall_transform = wall_curve.ComputeDerivatives(0.0, True)
        wall_origin = wall_transform.Origin
        wall_direction = wall_transform.BasisX

        # 2) Calcular ângulo em relação ao eixo X global (rotação planar)
        wall_rotation_angle = wall_direction.AngleTo(XYZ(1, 0, 0))
        if wall_direction.Y < 0:
            wall_rotation_angle = -wall_rotation_angle
        
        # 3) Converter a rotação da parede num quaternion "pai"
        parent_quat = quaternion_from_angle_z(wall_rotation_angle)

        # 4) Percorrer cada filho (porta ou janela)
        for child in data.findall('child'):
            structure_type = child.get('structure_type')
            if structure_type not in ['Door','Window', 'Alley']:
                continue
            
            # Dimensões (largura, altura, peitoril)
            width = meters_to_feet(float(child.find('width').text))
            height = meters_to_feet(float(child.find('height').text))

            parapet_val = None
            if structure_type == 'Window' or structure_type == 'Door':
                parapet_elem = child.find('parapet')
                if parapet_elem is not None:
                    parapet_val = meters_to_feet(float(parapet_elem.text)) # adiciona a elevação do nível
            
            # Posição local no XML (em metros) => converter para pés
            position_elem = child.find('position')
            x = meters_to_feet(float(position_elem.get('x')))
            y = meters_to_feet(float(position_elem.get('y')))
            z = meters_to_feet(float(position_elem.get('z')))
            local_point = XYZ(x, y, z)

            # Rotação local (XML) em quaternion
            rot_elem = child.find('rotation')
            if rot_elem is not None:
                w_rot = float(rot_elem.get('w'))
                x_rot = float(rot_elem.get('x'))
                y_rot = float(rot_elem.get('y'))
                z_rot = float(rot_elem.get('z'))
                child_quat = (w_rot, x_rot, y_rot, z_rot)
            else:
                # Se não houver rotação, assume quaternion identity
                child_quat = (1.0, 0.0, 0.0, 0.0)

            # 5) Combinar rotação do pai e do filho
            global_quat = parent_quat #quaternion_multiply(parent_quat, child_quat)

            # 6) Rotacionar o ponto local
            #    Aqui, pivot = (0,0,0), pois consideramos "local_point" relativo à base da parede
            rotated_local = apply_quaternion_rotation(local_point, XYZ(0,0,0), global_quat)

            # 7) Determinar a posição global (transladando pela origem da parede)
            global_x = wall_origin.X + rotated_local.X
            global_y = wall_origin.Y + rotated_local.Y
            global_z = wall_origin.Z + rotated_local.Z #Usa a elevação do nível diretamente, posiciona correto nos níveis

            # 8) Ajuste de alinhamento (janelas, r/l/c)
            if structure_type == 'Window':
                alignment_elem = child.find('alignment')
                alignment = alignment_elem.text.lower() if alignment_elem is not None else 'c'
                
                # Definindo offset local para "r","l","c"
                half_width = width / 2.0
                if alignment == 'r':
                    # por ex.: mover -half_width no eixo X local
                    offset_local = XYZ(half_width, 0, 0)
                elif alignment == 'l':
                    offset_local = XYZ(-half_width, 0, 0)
                else:
                    offset_local = XYZ(half_width, 0, 0)#XYZ(0, 0, 0)
                
                # Rotacionar esse offset_local pelo global_quat
                offset_rotated = apply_quaternion_rotation(offset_local, XYZ(0,0,0), global_quat)
                global_x += offset_rotated.X
                global_y += offset_rotated.Y

                # Ajusta a altura para posicionar a janela no meio
                global_z = height / 2.0
            
            elif structure_type in ['Door', 'Alley']:
                half_width = width / 2.0
                # Se quiser aplicar offset similar pra portas
                offset_local = XYZ(half_width, half_width, 0)
                offset_rotated = apply_quaternion_rotation(offset_local, XYZ(0,0,0), global_quat)
                global_x += offset_rotated.X
                global_y += offset_rotated.Y
                #global_z += offset_rotated.Z  # se necessário
                #pass

            # 9) Criar o ponto de inserção final e instanciar
            opening_point = XYZ(global_x, global_y, global_z)
            
            if structure_type == 'Door':
                family_symbol = door_family_symbol
            elif structure_type == 'Window':  # Window
                family_symbol = window_family_symbol
            else:
                family_symbol = alley_family_symbol

            opening_instance = doc.Create.NewFamilyInstance(
                opening_point,
                family_symbol,
                wall,
                Structure.StructuralType.NonStructural
            )
            created_element_ids.Add(opening_instance.Id)

            # 10) Ajustar parâmetros
            param_width = opening_instance.LookupParameter("Largura")
            if param_width:
                param_width.Set(width)
            
            param_height = opening_instance.LookupParameter("Altura")
            if param_height:
                param_height.Set(height)
            
            if parapet_val is not None:
                param_parapet = opening_instance.LookupParameter("Altura do peitoril")
                if param_parapet:
                    param_parapet.Set(parapet_val + float(level_elevation)) #+level.Elevation
            
            param_level = opening_instance.LookupParameter("Base Level")
            if param_level and not param_level.IsReadOnly:
                param_level.Set(level.Id)

    TransactionManager.Instance.TransactionTaskDone()


#####################################################################
# A partir daqui, executamos a lógica principal do script
#####################################################################

file_path = IN[0]
level_info = IN[1]
wall_family_name = UnwrapElement(IN[2])
door_family_name = UnwrapElement(IN[3])
window_family_name = UnwrapElement(IN[4])
alley_family_name  = UnwrapElement(IN[5])
xml_data = parse_xml(file_path)

doc = DocumentManager.Instance.CurrentDBDocument

lines = []
points = []
wall_data = []
heights = []

# Lista para armazenar todos os ElementIds criados
created_element_ids = List[ElementId]()

# Criando linhas a partir dos dados XML
for wall in xml_data.findall('object[@structure_type="Wall"]'):
    length = meters_to_feet(float(wall.find('length').text))
    height = meters_to_feet(float(wall.find('height').text))
    pos = wall.find('position')

    # Leitura das coordenadas originais
    x = meters_to_feet(float(pos.get('x')))
    y = meters_to_feet(float(pos.get('y')))
    z = meters_to_feet(float(pos.get('z')))

    original_start_point = DSPoint.ByCoordinates(x, y, z)

    rot = wall.find('rotation')

    # Leitura dos quaternions originais
    w = float(rot.get('w'))
    x_rot = float(rot.get('x'))
    y_rot = float(rot.get('y'))
    z_rot = float(rot.get('z'))

    rotation_quat = (w, x_rot, y_rot, z_rot)

    # Transformação dos quaternions
    rotation_quat = transform_quaternion(rotation_quat)

    # Criar e transformar a linha
    line_points = create_and_transform_line(original_start_point, length, rotation_quat)

    line = DSLine.ByStartPointEndPoint(line_points[0], line_points[1])
    lines.append(line)
    points.append(line_points[0])
    wall_data.append(wall)
    heights.append(height)

# Processar o nível
level_info = str(level_info)
level_name_match = re.search(r"Name=([^,]+),", level_info)
if level_name_match:
    level_name = level_name_match.group(1)
else:
    raise ValueError(f"Formato de nível inválido: {level_info}")

levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
level = next((lvl for lvl in levels if lvl.Name == level_name), None)

if level is None:
    raise ValueError(f"Nível com nome '{level_name}' não encontrado.")

# Criar paredes no Revit
walls = create_walls_in_revit(doc, lines, level, heights, wall_family_name, created_element_ids)

# Criar portas e janelas no Revit
create_openings_in_revit(doc, walls, wall_data, door_family_name, window_family_name, alley_family_name, created_element_ids, level)

# Agora, vamos agrupar todos os elementos criados usando a hora/minuto/segundo
TransactionManager.Instance.EnsureInTransaction(doc)
current_time = datetime.datetime.now()
# Formato de nome de grupo com H_M_S
group_name = "Grupo_{:02d}{:02d}{:02d}".format(current_time.hour, current_time.minute, current_time.second)

if created_element_ids.Count > 0:
    new_group = doc.Create.NewGroup(created_element_ids)
    new_group.GroupType.Name = group_name
TransactionManager.Instance.TransactionTaskDone()

# Output para visualização no Dynamo
OUT = (lines, points, level.Elevation)
