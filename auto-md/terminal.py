import argparse
import sys
from file_processor import process_input


def main():
    parser = argparse.ArgumentParser(description="Process text files.")
    parser.add_argument(
        "-i",
        "--input_paths",
        nargs="+",
        required=True,
        help="Input directories, text files, zip files, or GitHub repos.",
    )
    parser.add_argument(
        "-o", "--output_path", required=True, help="Output directory or file."
    )
    parser.add_argument(
        "-t",
        "--temp_folder",
        default="temp",
        help="Temporary folder for extracting zip files and cloning GitHub repos.",
    )
    parser.add_argument(
        "-s",
        "--single_file",
        action="store_true",
        help="Combine all processed files into a single output file.",
    )
    parser.add_argument(
        "-d",
        "--repo_depth",
        type=int,
        help="Depth for cloning GitHub repos. Useful for large repos.",
    )
    parser.add_argument(
        "-m",
        "--include_metadata",
        action="store_true",
        help="Include metadata (file path and title) in the output.",
    )
    parser.add_argument(
        "-c",
        "--include_toc",
        action="store_true",
        help="Include a table of contents at the beginning of the output.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print verbose output.",
    )
    parser.add_argument(
        "-ig",
        "--gitignore",
        type=str,
        help="Path to a .gitignore file to ignore certain files and directories.",
    )
    parser.add_argument(
        "-ip",
        "--ignore_paths",
        nargs="+",
        default=[],
        help="Additional paths to ignore.",
    )

    args = parser.parse_args()

    print(f"gitignore: {args.gitignore}")  # Add this line

    try:
        output_dir = process_input(
            args.input_paths,
            args.output_path,
            args.temp_folder,
            args.single_file,
            args.repo_depth,
            args.include_metadata,
            args.include_toc,
            args.verbose,
            args.gitignore,
            args.ignore_paths,
        )
        print(f"Processed files saved to: {output_dir}")
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
