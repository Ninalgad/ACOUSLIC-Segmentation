"""
The following is a the inference code for running the baseline algorithm.

It is meant to run within a container.

To run it locally, you can call the following bash script:

  ./test_run.sh

This will start the inference and reads from ./test/input and outputs to ./test/output

To export the container and prep it for upload to Grand-Challenge.org you can call:

  docker save example-algorithm-preliminary-development-phase | gzip -c > example-algorithm-preliminary-development-phase.tar.gz

Any container that shows the same behavior will do, this is purely an example of how one COULD do it.

Happy programming!
"""
import json
import os
from glob import glob
from pathlib import Path

import numpy as np
import SimpleITK
import click
from model import FetalAbdomenSegmentation


@click.command()
@click.option('--input-path', '-i', type=str, default="/input")
@click.option('--output-path', '-o', type=str, default="/output")
@click.option('--resource-path', '-r', type=str, default="resources")
@click.option('--debug', is_flag=True, show_default=True, default=False)
def run(input_path, output_path, resource_path, debug):
    input_path = Path(input_path)
    output_path = Path(output_path)
    resource_path = Path(resource_path)

    # Read the input
    stacked_fetal_ultrasound_path = get_image_file_path(
        location=input_path / "images/stacked-fetal-ultrasound")

    # Process the inputs: any way you'd like
    _show_torch_cuda_info()

    fetal_abdomen_map, frame_probability = 0., 0.
    checkpoints = glob(f"{resource_path}/*.pt")
    algorithm = FetalAbdomenSegmentation()

    for chkpt_path in checkpoints:
        # Instantiate the algorithm
        algorithm.load_checkpoint(chkpt_path)

        # Forward pass
        s, f = algorithm.predict(
            stacked_fetal_ultrasound_path, debug=debug)  # (372, 281, 840), (840,)

        # Postprocess the output
        s, f = algorithm.postprocess(s, f)  # (840, 562, 744), (840,)

        fetal_abdomen_map += s
        frame_probability += f
        del s, f

    del algorithm

    # Majority voted pixels are segmented
    cutoff = max(1, int(len(checkpoints) // 2))
    fetal_abdomen_map = (fetal_abdomen_map >= cutoff).astype("uint8")

    # Select the fetal abdomen mask and the corresponding frame number
    fetal_abdomen_frame_number, fetal_abdomen_segmentation = get_suitable_frame(
        frame_probability, fetal_abdomen_map)

    # Save your output
    write_array_as_image_file(
        location=output_path / "images/fetal-abdomen-segmentation",
        array=fetal_abdomen_segmentation,
        frame_number=fetal_abdomen_frame_number,
    )
    write_json_file(
        location=output_path / "fetal-abdomen-frame-number.json",
        content=fetal_abdomen_frame_number
    )

    # Print the output
    print("output folder contents:")
    print_directory_contents(output_path)

    # Print shape and type of the output
    print("\nprinting output shape and type:")
    print(f"shape: {fetal_abdomen_segmentation.shape}")
    print(f"type: {type(fetal_abdomen_segmentation)}")
    print(f"dtype: {fetal_abdomen_segmentation.dtype}")
    print(f"unique values: {np.unique(fetal_abdomen_segmentation)}")
    print(f"frame number: {fetal_abdomen_frame_number}")
    print(type(fetal_abdomen_frame_number))

    return 0


def get_suitable_frame(frame_probabilities, segmentation_map, sweep_width=15):
    # Get the optimal frame number and segmentation predictions
    n = int(np.argmax(frame_probabilities))
    n_frames = len(frame_probabilities)

    if segmentation_map[n].max() == 0:
        # check frames within `sweep_width` for a positive segmentation map
        for i in range(1, sweep_width):
            j = np.clip(n + i, 0, n_frames-1)
            if segmentation_map[j].max() > 0:
                return j, segmentation_map[j]

            j = np.clip(n - i, 0, n_frames-1)
            if segmentation_map[j].max() > 0:
                return j, segmentation_map[j]

        return -1, np.zeros_like(segmentation_map[0])

    return n, segmentation_map[n]


def write_json_file(*, location, content):
    # Writes a json file
    with open(location, 'w') as f:
        f.write(json.dumps(content, indent=4))


def load_image_file_as_array(*, location):
    # Use SimpleITK to read a file
    input_files = glob(str(location / "*.tiff")) + \
                  glob(str(location / "*.mha"))
    result = SimpleITK.ReadImage(input_files[0])

    # Convert it to a Numpy array
    return SimpleITK.GetArrayFromImage(result)


# Get image file path from input folder
def get_image_file_path(*, location):
    input_files = glob(str(location / "*.tiff")) + \
                  glob(str(location / "*.mha"))
    return input_files[0]


def write_array_as_image_file(*, location, array, frame_number=None):
    location.mkdir(parents=True, exist_ok=True)
    suffix = ".mha"
    # Assert that the array is 2D
    assert array.ndim == 2, f"Expected a 2D array, got {array.ndim}D."

    # Convert the 2D mask to a 3D mask (this is solely for visualization purposes)
    array = convert_2d_mask_to_3d(
        mask_2d=array,
        frame_number=frame_number,
        number_of_frames=840,
    )

    image = SimpleITK.GetImageFromArray(array)
    # Set the spacing to 0.28mm in all directions
    image.SetSpacing([0.28, 0.28, 0.28])
    SimpleITK.WriteImage(
        image,
        location / f"output{suffix}",
        useCompression=True,
    )


def convert_2d_mask_to_3d(*, mask_2d, frame_number, number_of_frames):
    # Convert a 2D mask to a 3D mask
    mask_3d = np.zeros((number_of_frames, *mask_2d.shape), dtype=np.uint8)
    # If frame_number == -1, return a 3D mask with all zeros
    if frame_number == -1:
        return mask_3d
    # If frame_number is within the valid range, set the corresponding frame to the 2D mask
    if frame_number is not None and 0 <= frame_number < number_of_frames:
        mask_3d[frame_number, :, :] = mask_2d
        return mask_3d
    # If frame_number is None or out of bounds, raise a ValueError
    else:
        raise ValueError(
            f"frame_number must be between -1 and {number_of_frames - 1}, got {frame_number}."
        )


def print_directory_contents(path):
    for child in os.listdir(path):
        child_path = os.path.join(path, child)
        if os.path.isdir(child_path):
            print_directory_contents(child_path)
        else:
            print(child_path)


def _show_torch_cuda_info():
    import torch
    print("=+=" * 10)
    print("Collecting Torch CUDA information")
    print(
        f"Torch CUDA is available: {(available := torch.cuda.is_available())}")
    if available:
        print(f"\tnumber of devices: {torch.cuda.device_count()}")
        print(
            f"\tcurrent device: {(current_device := torch.cuda.current_device())}")
        print(
            f"\tproperties: {torch.cuda.get_device_properties(current_device)}")
    print("=+=" * 10)


if __name__ == "__main__":
    raise SystemExit(run())
