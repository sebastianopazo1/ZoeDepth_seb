import torch
from PIL import Image
import numpy as np
from zoedepth.models.builder import build_model
from zoedepth.utils.config import get_config
from zoedepth.utils.geometry import depth_to_points
import open3d as o3d


def resize_image(image, max_size=(1024, 1024)):
    """
    Redimensiona la imagen manteniendo la proporción hasta que su lado más largo sea max_size.
    """
    image.thumbnail(max_size, Image.ANTIALIAS)
    return image

def process_four_cameras(image_path1, image_path2, image_path3, image_path4, model_name="zoedepth", depth_threshold=2.0):
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device for model inference: {DEVICE}")

    # Inicializar modelo
    conf = get_config(model_name, "infer")
    model = build_model(conf).to(DEVICE)
    model.eval()

    # Definir transformaciones para cada cámara
    T_cam1_world = np.eye(4)  # Cámara 1 (referencia)
    T_cam2_world = np.array([[1, 0, 0, 0],
                            [0, 1, 0, -0.4],
                            [0, 0, 1, 0],
                            [0, 0, 0, 1]])
    T_cam3_world = np.array([[1, 0, 0, 0],
                            [0, 1, 0, -0.78],
                            [0, 0, 1, 0],
                            [0, 0, 0, 1]])
    T_cam4_world = np.array([[1, 0, 0, 0],
                            [0, 1, 0, -1.13],
                            [0, 0, 1, 0],
                            [0, 0, 0, 1]])

    with torch.no_grad():
        # Procesar las cuatro imágenes
        images = []
        depths = []
        for img_path in [image_path1, image_path2, image_path3, image_path4]:
            img = Image.open(img_path).convert("RGB")
            img = resize_image(img, max_size=(1024, 1024))
            depth = model.infer_pil(img)
            images.append(np.array(img))
            depths.append(depth)

    # Encontrar la profundidad mínima (puntos más cercanos) para cada imagen
    min_depths = []
    for depth in depths:
        points = depth_to_points(depth[None])
        points_flat = points.reshape(-1, 3)
        min_z = np.percentile(points_flat[:, 2], 5)  # Usar percentil 5 para evitar valores atípicos
        min_depths.append(min_z)

    # Calcular los offsets para alinear los puntos más cercanos
    base_depth = min_depths[0]  # Usar la primera imagen como referencia
    depth_offsets = [d - base_depth for d in min_depths]

    # Modificar las matrices de transformación para incluir el offset en Z
    transforms = []
    base_transforms = [T_cam1_world, T_cam2_world, T_cam3_world, T_cam4_world]
    for i, base_transform in enumerate(base_transforms):
        transform = base_transform.copy()
        transform[2, 3] = depth_offsets[i]  # Agregar offset en Z
        transforms.append(transform)

    pcds = []
    for i in range(4):
        points = depth_to_points(depths[i][None])
        points_flat = points.reshape(-1, 3)
        
        # Filtrar puntos basados en la profundidad (mostrar solo los más cercanos)
        mask = points_flat[:, 2] < depth_threshold
        points_filtered = points_flat[mask]
        
        # Transformar puntos a coordenadas globales
        points_homogeneous = np.concatenate([points_filtered, np.ones((points_filtered.shape[0], 1))], axis=1)
        points_world = (transforms[i] @ points_homogeneous.T).T[:, :3]

        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points_world.astype(np.float32))
        
        # Filtrar colores correspondientes
        colors = (images[i].reshape(-1, 3)[mask] / 255.0).astype(np.float32)
        pcd.colors = o3d.utility.Vector3dVector(colors)
        pcds.append(pcd)

    # Visualización
    vis = o3d.visualization.Visualizer()
    vis.create_window(width=1280, height=720)

    # Agregar las nubes de puntos
    for pcd in pcds:
        vis.add_geometry(pcd)

    # Agregar sistemas de coordenadas para cada cámara
    for i, transform in enumerate(transforms):
        coord_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.3)
        coord_frame.transform(transform)
        vis.add_geometry(coord_frame)

    opt = vis.get_render_option()
    opt.point_size = 1.0
    opt.background_color = np.asarray([0, 0, 0])

    vis.run()
    vis.destroy_window()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Procesamiento de cuatro cámaras')
    parser.add_argument('--image1', required=True, help='Imagen de camara 1 (origen)')
    parser.add_argument('--image2', required=True, help='Imagen de camara 2 (38cm abajo)')
    parser.add_argument('--image3', required=True, help='Imagen de camara 3 (76cm abajo)')
    parser.add_argument('--image4', required=True, help='Imagen de camara 4 (114cm abajo)')
    parser.add_argument('--model', default='zoedepth', help='Modelo a utilizar')
    parser.add_argument('--threshold', type=float, default=2.0, help='Umbral de profundidad máxima')
    
    args = parser.parse_args()
    process_four_cameras(args.image1, args.image2, args.image3, args.image4, args.model, args.threshold)