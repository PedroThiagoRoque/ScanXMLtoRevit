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

# Função para converter metros para pés
def meters_to_feet(meters):
    return meters * 3.28084

# Função para ler o arquivo XML
def parse_xml(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()
    return root

# Função para multiplicar dois quaternions
def quaternion_multiply(q1, q2):
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    w = w1*w2 - x1*x2 - y1*y2 - z1*z2
    x = w1*x2 + x1*w2 + y1*z2 - z1*y2
    y = w1*y2 - x1*z2 + y1*w2 + z1*x2
    z = w1*z2 + x1*y2 - y1*x2 + z1*w2
    return (w, x, y, z)

# Função para calcular o conjugado de um quaternion
def quaternion_conjugate(q):
    w, x, y, z = q
    return (w, -x, -y, -z)

# Função para aplicar rotação de um ponto usando quaternion
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
    
    return DSPoint.ByCoordinates(new_x, new_y, new_z)

# Função para transformar um ponto do sistema XML para o sistema Dynamo
def transform_point(point):
    x_new = point.X
    y_new = -point.Z # correção eficaz para o posicionamento
    z_new = point.Y
    return DSPoint.ByCoordinates(x_new, y_new, z_new)

# Função para transformar um quaternion do sistema XML para o sistema Dynamo
def transform_quaternion(q):
    w, x, y, z = q
    return (w, x, z, y)  # Trocar Y por Z

# Função para criar a linha base e aplicar a transformação
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

###################################################################

def activate_family_symbol(family_symbol):
    if not family_symbol.IsActive:
        family_symbol.Activate()
        DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument.Document.Regenerate()

# Função para criar paredes no Revit
def create_walls_in_revit(doc, lines, level, heights, wall_family_name):
    TransactionManager.Instance.EnsureInTransaction(doc)
    walls = []
    for line, height in zip(lines, heights):
        start_point = line.StartPoint
        end_point = line.EndPoint
        revit_line = Line.CreateBound(XYZ(start_point.X, start_point.Y, start_point.Z), XYZ(end_point.X, end_point.Y, end_point.Z))
        wall = Wall.Create(doc, revit_line, wall_family_name.Id, level.Id, height, 0.0, False, False)
        walls.append(wall)
    TransactionManager.Instance.TransactionTaskDone()
    return walls


def create_openings_in_revit(doc, walls, wall_data, door_family_symbol, window_family_symbol):
    activate_family_symbol(door_family_symbol)
    activate_family_symbol(window_family_symbol)
    
    TransactionManager.Instance.EnsureInTransaction(doc)
    for wall, data in zip(walls, wall_data):
        # Recupera a rotação e a posição da parede
        wall_transform = wall.Location.Curve.ComputeDerivatives(0.0, True)
        wall_origin = wall_transform.Origin
        wall_direction = wall_transform.BasisX
        wall_rotation_angle = wall_direction.AngleTo(XYZ(1, 0, 0))
        if wall_direction.Y < 0:
            wall_rotation_angle = -wall_rotation_angle

        for child in data.findall('child'):
            structure_type = child.get('structure_type')
            position = child.find('position')
            width = meters_to_feet(float(child.find('width').text))
            height = meters_to_feet(float(child.find('height').text))
            # Para janelas, lê o valor do peitoril (<parapet>)
            parapet_val = None
            if structure_type == 'Window':
                parapet_elem = child.find('parapet')
                if parapet_elem is not None:
                    parapet_val = meters_to_feet(float(parapet_elem.text))
            
            # Lê as coordenadas
            x = meters_to_feet(float(position.get('x')))
            y = meters_to_feet(float(position.get('y')))
            z = meters_to_feet(float(position.get('z')))
            
            # Ponto local do objeto
            local_point = XYZ(x, y, z)
            
            # Aplica rotação local (se houver)
            rot = child.find('rotation')
            if rot is not None:
                w_rot = float(rot.get('w'))
                x_rot = float(rot.get('x'))
                y_rot = float(rot.get('y'))
                z_rot = float(rot.get('z'))
                door_rotation_quat = (w_rot, x_rot, y_rot, z_rot)
                # Conversão para ângulo (supondo rotação em Z)
                door_rotation_angle = 2 * math.acos(w_rot)
            else:
                door_rotation_angle = 0

            # Converte a posição local para posição global (com base na parede)
            cos_angle = math.cos(wall_rotation_angle)
            sin_angle = math.sin(wall_rotation_angle)
            global_x = wall_origin.X + (local_point.X * cos_angle - local_point.Y * sin_angle)
            global_y = wall_origin.Y + (local_point.X * sin_angle + local_point.Y * cos_angle)
            global_z = wall_origin.Z + local_point.Z

            # Lógica de posicionamento e seleção de família
            if structure_type == 'Door':
                family_symbol = door_family_symbol
                # Para portas, consideramos o ponto global calculado sem ajuste
                opening_point = XYZ(global_x, global_y, global_z)
            elif structure_type == 'Window':
                family_symbol = window_family_symbol
                # --- Cálculo para janelas ---
                # A partir do XML, o ponto (global_x, global_y, global_z) pode ser interpretado
                # como a extremidade (início) da janela. Porém, como os parâmetros de largura e altura
                # serão aplicados a partir do centro do objeto, devemos reajustar o ponto para ser o centro.
                
                # 1. Leitura do alinhamento: 
                #    - 'r': o XML indica o início da janela à esquerda, de modo que a janela se estende para a direita.
                #    - 'l': o XML indica o início da janela à direita, de modo que a janela se estende para a esquerda.
                #    - 'c' (ou sem informação): o ponto já é o centro.
                alignment_elem = child.find('alignment')
                alignment = alignment_elem.text.lower() if alignment_elem is not None else 'c'
                
                # 2. Para o cálculo horizontal usamos o vetor unitário na direção da janela,
                #    dado pelo ângulo de rotação (door_rotation_angle). 
                #    Calculamos o deslocamento horizontal de metade da largura.
                half_width = width / 2.0
                if alignment == 'r':
                    # Se 'r': o XML indica o início (lado esquerdo); o centro está à direita (soma do deslocamento)
                    center_x = global_x - half_width * math.cos(door_rotation_angle)
                    center_y = global_y - half_width * math.sin(door_rotation_angle)
                elif alignment == 'l':
                    # Se 'l': o XML indica o início (lado direito); o centro está à esquerda (subtração)
                    center_x = global_x + half_width * math.cos(door_rotation_angle)
                    center_y = global_y + half_width * math.sin(door_rotation_angle)
                else:  # 'c' ou qualquer outro valor: assume que o ponto já é o centro horizontal
                    center_x = global_x
                    center_y = global_y
                
                # 3. Ajuste vertical: supondo que o XML defina o ponto na base da janela,
                #    elevamos o ponto em metade da altura para centralizar verticalmente.
                center_z = global_z + (height / 2.0)
                
                # Define o ponto final de inserção para a janela como seu centro
                opening_point = XYZ(center_x, center_y, center_z)
            else:
                continue  # Ignora se não for porta nem janela



            # Cria a instância da família
            opening_instance = doc.Create.NewFamilyInstance(opening_point, family_symbol, wall, Structure.StructuralType.NonStructural)
            
            # Rotaciona a abertura se necessário (apenas para portas, normalmente)
            if door_rotation_angle != 0 and structure_type == 'Door':
                axis = Line.CreateUnbound(opening_point, XYZ.BasisZ)
                ElementTransformUtils.RotateElement(doc, opening_instance.Id, axis, door_rotation_angle)
            
            # Para janelas, atualiza os parâmetros de largura, altura e peitoril
            if structure_type == 'Window':
                
                param_width = opening_instance.LookupParameter("Largura")
                if param_width:
                    param_width.Set(width)

                param_height = opening_instance.LookupParameter("Altura")
                if param_height:
                    param_height.Set(height)

                if parapet_val is not None:
                    param_parapet = opening_instance.LookupParameter("Altura do peitoril")
                    if param_parapet:
                        param_parapet.Set(parapet_val)
    TransactionManager.Instance.TransactionTaskDone()



#####################################################################

# Lendo o arquivo XML
file_path = IN[0]
level_info = IN[1]
wall_family_name = UnwrapElement(IN[2])
door_family_name = UnwrapElement(IN[3])
window_family_name = UnwrapElement(IN[4])
xml_data = parse_xml(file_path)

doc = DocumentManager.Instance.CurrentDBDocument

lines = []
points = []
wall_data = []
heights = []

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
    points.append(line_points[0])  # Adicionar o ponto inicial transformado para visualização
    wall_data.append(wall)
    heights.append(height)

# Processar o nível
# Certifique-se de que level_info é uma string
level_info = str(level_info)
level_name_match = re.search(r"Name=([^,]+),", level_info)
if level_name_match:
    level_name = level_name_match.group(1)
else:
    raise ValueError(f"Invalid level format: {level_info}")

levels = FilteredElementCollector(doc).OfClass(Level).ToElements()
level = next((lvl for lvl in levels if lvl.Name == level_name), None)

if level is None:
    raise ValueError(f"Level with name '{level_name}' not found.")

# Criar paredes no Revit com base nas linhas e alturas
walls = create_walls_in_revit(doc, lines, level, heights, wall_family_name)

# Criar portas e janelas no Revit com base nas paredes e nos dados do XML
create_openings_in_revit(doc, walls, wall_data, door_family_name, window_family_name)
# Output para visualização no Dynamo
OUT = (lines, points)
