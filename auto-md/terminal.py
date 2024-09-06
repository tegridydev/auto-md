import sys
import argparse
from file_processor import process_input


def main():
    parser = argparse.ArgumentParser(
        description="Process input files or repositories into Markdown format."
    )
    parser.add_argument(
        "input_paths", nargs="+", help="Paths to input files or repositories."
    )
    parser.add_argument(
        "-o", "--output_path", required=True, help="Output directory or file path."
    )
    parser.add_argument(
        "-t",
        "--temp_folder",
        default="temp",
        help="Temporary folder for storing intermediate data.",
    )
    parser.add_argument(
        "-s",
        "--single_file",
        action="store_true",
        help="Combine all processed files into a single Markdown file.",
    )
    parser.add_argument(
        "-d",
        "--repo_depth",
        type=int,
        help="Depth of the repository to clone (for GitHub repos).",
    )
    parser.add_argument(
        "-m",
        "--include_metadata",
        action="store_true",
        default=True,
        help="Include metadata in the output Markdown files.",
    )
    parser.add_argument(
        "-c",
        "--include_toc",
        action="store_true",
        default=True,
        help="Include table of contents in the output Markdown files.",
    )

    args = parser.parse_args()

    try:
        output_dir = process_input(
            args.input_paths,
            args.output_path,
            args.temp_folder,
            args.single_file,
            args.repo_depth,
            args.include_metadata,
            args.include_toc,
        )
        print(f"Processed files saved to: {output_dir}")
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
