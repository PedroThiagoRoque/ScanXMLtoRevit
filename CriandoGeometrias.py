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
    new_y = -rotated_p[2] + origin.Y
    new_z = rotated_p[3] + origin.Z
    
    return DSPoint.ByCoordinates(new_x, new_y, new_z)

# Função para criar a linha base e aplicar a rotação
def create_and_transform_line(start_point, length, rotation_quat):
    # Criar ponto final da linha no plano XY
    end_point = DSPoint.ByCoordinates(start_point.X + length, start_point.Y, start_point.Z)
    
    # Aplicar rotação ao ponto final
    rotated_end_point = apply_quaternion_rotation(end_point, start_point, rotation_quat)
    
    return [start_point, rotated_end_point]

# Função para criar paredes no Revit
def create_walls_in_revit(doc, lines, level, height, wall_family_name):
    TransactionManager.Instance.EnsureInTransaction(doc)
    walls = []
    for line in lines:
        start_point = line.StartPoint
        end_point = line.EndPoint
        revit_line = Line.CreateBound(XYZ(start_point.X, start_point.Y, start_point.Z), XYZ(end_point.X, end_point.Y, end_point.Z))
        wall = Wall.Create(doc, revit_line, wall_family_name.Id, level.Id, height, 0.0, False, False)
        walls.append(wall)
    TransactionManager.Instance.TransactionTaskDone()
    return walls

# Função para ativar um FamilySymbol
def activate_family_symbol(family_symbol):
    if not family_symbol.IsActive:
        family_symbol.Activate()
        DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument.Document.Regenerate()

# Função para criar portas e janelas no Revit
def create_openings_in_revit(doc, walls, wall_data, door_family_name, window_family_name):
    activate_family_symbol(door_family_name)
    activate_family_symbol(window_family_name)
    
    TransactionManager.Instance.EnsureInTransaction(doc)
    for wall, data in zip(walls, wall_data):
        for child in data.findall('child'):
            structure_type = child.get('structure_type')
            if structure_type == 'Door':
                position = child.find('position')
                width = meters_to_feet(float(child.find('width').text))
                height = meters_to_feet(float(child.find('height').text))
                x = meters_to_feet(float(position.get('x')))
                z = meters_to_feet(float(position.get('y')))  # Z do XML vai para Y
                y = meters_to_feet(float(position.get('z')))  # Y do XML vai para Z
                door_point = XYZ(x, y, z)
                door_instance = doc.Create.NewFamilyInstance(door_point, door_family_name, wall, Structure.StructuralType.NonStructural)
            elif structure_type == 'Window':
                position = child.find('position')
                width = meters_to_feet(float(child.find('width').text))
                height = meters_to_feet(float(child.find('height').text))
                x = meters_to_feet(float(position.get('x')))
                z = meters_to_feet(float(position.get('y')))  # Z do XML vai para Y
                y = meters_to_feet(float(position.get('z')))  # Y do XML vai para Z
                window_point = XYZ(x - width / 2, y, z)  # Ajuste para centralizar a janela
                window_instance = doc.Create.NewFamilyInstance(window_point, window_family_name, wall, Structure.StructuralType.NonStructural)
    TransactionManager.Instance.TransactionTaskDone()

# Lendo o arquivo XML
file_path = IN[0]
level_info = IN[1]
wall_family_name = UnwrapElement(IN[2])
door_family_name = UnwrapElement(IN[3])
window_family_name = UnwrapElement(IN[4])
xml_data = parse_xml(file_path)

doc = DocumentManager.Instance.CurrentDBDocument

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

lines = []
points = []
wall_data = []

# Criando linhas a partir dos dados XML
for wall in xml_data.findall('object[@structure_type="Wall"]'):
    length = meters_to_feet(float(wall.find('length').text))
    height = meters_to_feet(float(wall.find('height').text))
    pos = wall.find('position')
    x = meters_to_feet(float(pos.get('x')))
    z = meters_to_feet(float(pos.get('y')))  # Z do XML vai para Y
    y = meters_to_feet(float(pos.get('z')))  # Y do XML vai para Z
    
    start_point = DSPoint.ByCoordinates(x, y, z)
    
    rot = wall.find('rotation')
    w = float(rot.get('w'))
    x_rot = float(rot.get('x'))
    z_rot = float(rot.get('y'))  # Z do XML vai para Y
    y_rot = float(rot.get('z'))  # Y do XML vai para Z
    
    rotation_quat = (w, x_rot, z_rot, y_rot)
    
    # Criar e transformar a linha
    line_points = create_and_transform_line(start_point, length, rotation_quat)
    
    line = DSLine.ByStartPointEndPoint(line_points[0], line_points[1])
    lines.append(line)
    points.append(start_point)  # Adicionar o ponto de posição para visualização
    wall_data.append(wall)

# Criar paredes no Revit com base nas linhas
walls = create_walls_in_revit(doc, lines, level, height, wall_family_name)

# Criar portas e janelas no Revit com base nas paredes e nos dados do XML
create_openings_in_revit(doc, walls, wall_data, door_family_name, window_family_name)

# Output para visualização no Dynamo
OUT = (lines, points)
