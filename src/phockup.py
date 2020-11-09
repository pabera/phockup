#!/usr/bin/env python3
import hashlib
import os
import re
import shutil
import sys

from src.date import Date
from src.exif import Exif
from src.printer import Printer

printer = Printer()
ignored_files = (".DS_Store", "Thumbs.db")


class Phockup():
    def __init__(self, input, output, **args):
        input = os.path.expanduser(input)
        output = os.path.expanduser(output)

        if input.endswith(os.path.sep):
            input = input[:-1]
        if output.endswith(os.path.sep):
            output = output[:-1]

        self.input = input
        self.output = output
        self.dir_format = args.get('dir_format', os.path.sep.join(['%Y', '%m', '%d']))
        self.move = args.get('move', False)
        self.link = args.get('link', False)
        self.original_filenames = args.get('original_filenames', False)
        self.date_regex = args.get('date_regex', None)
        self.timestamp = args.get('timestamp', False)
        self.date_field = args.get('date_field', False)
        self.dry_run = args.get('dry_run', False)
        self.file_type = args.get('file_type', None)
        self.ignore_unknowns = args.get('ignore_unknowns', None)

        self.check_directories()
        self.walk_directory()

    def check_directories(self):
        """
        Check if input and output directories exist.
        If input does not exists it exits the process
        If output does not exists it tries to create it or exit with error
        """
        if not os.path.isdir(self.input) or not os.path.exists(self.input):
            printer.error('Input directory "%s" does not exist or cannot be accessed' % self.input)
            return
        if not os.path.exists(self.output):
            printer.line('Output directory "%s" does not exist, creating now' % self.output)
            try:
                if not self.dry_run:
                    os.makedirs(self.output)
            except Exception:
                printer.error('Cannot create output directory. No write access!')

    def walk_directory(self):
        """
        Walk input directory recursively and call process_file for each file except the ignored ones
        """
        for root, _, files in os.walk(self.input):
            files.sort()
            for filename in files:
                if filename in ignored_files:
                    continue

                file = os.path.join(root, filename)
                self.process_file(file)

    def checksum(self, file):
        """
        Calculate checksum for a file.
        Used to match if duplicated file name is actually a duplicated file
        """
        block_size = 65536
        sha256 = hashlib.sha256()
        with open(file, 'rb') as f:
            for block in iter(lambda: f.read(block_size), b''):
                sha256.update(block)
        return sha256.hexdigest()

    def get_file_type(self, mimetype):
        """
        Check if given file_type is image or video
        Return None if other
        """
        patternImage = re.compile('^(image/.+|application/vnd.adobe.photoshop)$')
        if patternImage.match(mimetype):
            return 'image'

        patternVideo = re.compile('^(video/.*)$')
        if patternVideo.match(mimetype):
            return 'video'
        return None


    def get_output_dir(self, date):
        """
        Generate output directory path based on the extracted date and formatted using dir_format
        If date is missing from the exifdata the file is going to "unknown" directory
        unless user included a regex from filename or uses timestamp
        """
        try:
            path = [self.output, date['date'].date().strftime(self.dir_format)]
        except:
            path = [self.output, 'unknown']

        fullpath = os.path.sep.join(path)

        if not os.path.isdir(fullpath) and not self.dry_run:
            os.makedirs(fullpath)

        return fullpath

    def get_file_name(self, file, date):
        """
        Generate file name based on exif data unless it is missing or
        original filenames are required. Then use original file name
        """
        if self.original_filenames:
            return os.path.basename(file)

        try:
            filename = [
                '%04d' % date['date'].year,
                '%02d' % date['date'].month,
                '%02d' % date['date'].day,
                '-',
                '%02d' % date['date'].hour,
                '%02d' % date['date'].minute,
                '%02d' % date['date'].second,
            ]

            if date['subseconds']:
                filename.append(date['subseconds'])

            return ''.join(filename) + os.path.splitext(file)[1]
        except:
            return os.path.basename(file)

    def process_file(self, file):
        """
        Process the file using the selected strategy
        If file is .xmp skip it so process_xmp method can handle it
        """
        if str.endswith(file, '.xmp'):
            return None

        printer.line(file, True)

        output, target_file_name, target_file_path, target_file_type = self.get_file_name_and_path(file)

        suffix = 1
        target_file = target_file_path

        while True:
            if self.file_type != target_file_type:
                if self.file_type is not None:
                    printer.line(' => skipped, file is %s but should be %s' % (target_file_type, self.file_type))
                    break

            if os.path.isfile(target_file):
                if self.checksum(file) == self.checksum(target_file):
                    printer.line(' => skipped, duplicated file %s' % target_file)
                    break
            else:
                if not self.dry_run:
                    if self.move:
                        try:
                            shutil.move(file, target_file)
                        except FileNotFoundError:
                            printer.line(' => skipped, no such file or directory')
                            break
                    elif self.link:
                        os.link(file, target_file)
                    else:
                        try:
                            shutil.copy2(file, target_file)
                        except FileNotFoundError:
                            printer.line(' => skipped, no such file or directory')
                            break

                printer.line(' => %s' % target_file)
                self.process_xmp(file, target_file_name, suffix, output)
                break

            suffix += 1
            target_split = os.path.splitext(target_file_path)
            target_file = "%s-%d%s" % (target_split[0], suffix, target_split[1])

    def get_file_name_and_path(self, file):
        """
        Returns target file name and path
        """
        exif_data = Exif(file).data()
        target_file_type = None

        if exif_data and 'MIMEType' in exif_data:
            target_file_type = self.get_file_type(exif_data['MIMEType'])

        if target_file_type in ['image', 'video']:
            date = Date(file).from_exif(exif_data, self.timestamp, self.date_regex, self.date_field)
            output = self.get_output_dir(date)
            target_file_name = self.get_file_name(file, date)
            if not self.original_filenames:
                target_file_name = target_file_name.lower()
            target_file_path = os.path.sep.join([output, target_file_name])
        else:
            output = self.get_output_dir(False)
            target_file_name = os.path.basename(file)
            target_file_path = os.path.sep.join([output, target_file_name])

        return output, target_file_name, target_file_path, target_file_type

    def process_xmp(self, file, file_name, suffix, output):
        """
        Process xmp files. These are meta data for RAW images
        """
        xmp_original_with_ext = file + '.xmp'
        xmp_original_without_ext = os.path.splitext(file)[0] + '.xmp'

        suffix = '-%s' % suffix if suffix > 1 else ''

        xmp_files = {}

        if os.path.isfile(xmp_original_with_ext):
            xmp_target = '%s%s.xmp' % (file_name, suffix)
            xmp_files[xmp_original_with_ext] = xmp_target
        if os.path.isfile(xmp_original_without_ext):
            xmp_target = '%s%s.xmp' % (os.path.splitext(file_name)[0], suffix)
            xmp_files[xmp_original_without_ext] = xmp_target

        for original, target in xmp_files.items():
            xmp_path = os.path.sep.join([output, target])
            printer.line('%s => %s' % (original, xmp_path))

            if not self.dry_run:
                if self.move:
                    shutil.move(original, xmp_path)
                elif self.link:
                    os.link(original, xmp_path)
                else:
                    shutil.copy2(original, xmp_path)
