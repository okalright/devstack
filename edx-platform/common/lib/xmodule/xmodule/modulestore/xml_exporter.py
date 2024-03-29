"""
Methods for exporting course data to XML
"""

import logging
import lxml.etree
from xblock.fields import Scope, Reference, ReferenceList, ReferenceValueDict
from xmodule.contentstore.content import StaticContent
from xmodule.exceptions import NotFoundError
from xmodule.modulestore import EdxJSONEncoder, ModuleStoreEnum
from xmodule.modulestore.inheritance import own_metadata
from xmodule.modulestore.store_utilities import draft_node_constructor, get_draft_subtree_roots
from fs.osfs import OSFS
from json import dumps
import json
import os
from path import path
import shutil
from xmodule.modulestore.draft_and_published import DIRECT_ONLY_CATEGORIES
from opaque_keys.edx.locator import CourseLocator

DRAFT_DIR = "drafts"
PUBLISHED_DIR = "published"
EXPORT_VERSION_FILE = "format.json"
EXPORT_VERSION_KEY = "export_format"

DEFAULT_CONTENT_FIELDS = ['metadata', 'data']


def export_to_xml(modulestore, contentstore, course_key, root_dir, course_dir):
    """
    Export all modules from `modulestore` and content from `contentstore` as xml to `root_dir`.

    `modulestore`: A `ModuleStore` object that is the source of the modules to export
    `contentstore`: A `ContentStore` object that is the source of the content to export, can be None
    `course_key`: The `CourseKey` of the `CourseModuleDescriptor` to export
    `root_dir`: The directory to write the exported xml to
    `course_dir`: The name of the directory inside `root_dir` to write the course content to
    """

    with modulestore.bulk_operations(course_key):

        course = modulestore.get_course(course_key, depth=None)  # None means infinite
        fsm = OSFS(root_dir)
        export_fs = course.runtime.export_fs = fsm.makeopendir(course_dir)

        root = lxml.etree.Element('unknown')

        # export only the published content
        with modulestore.branch_setting(ModuleStoreEnum.Branch.published_only, course_key):
            # change all of the references inside the course to use the xml expected key type w/o version & branch
            xml_centric_course_key = CourseLocator(course_key.org, course_key.course, course_key.run, deprecated=True)
            adapt_references(course, xml_centric_course_key, export_fs)

            course.add_xml_to_node(root)

        with export_fs.open('course.xml', 'w') as course_xml:
            lxml.etree.ElementTree(root).write(course_xml)

        # export the static assets
        policies_dir = export_fs.makeopendir('policies')
        if contentstore:
            contentstore.export_all_for_course(
                course_key,
                root_dir + '/' + course_dir + '/static/',
                root_dir + '/' + course_dir + '/policies/assets.json',
            )

            # If we are using the default course image, export it to the
            # legacy location to support backwards compatibility.
            if course.course_image == course.fields['course_image'].default:
                try:
                    course_image = contentstore.find(
                        StaticContent.compute_location(
                            course.id,
                            course.course_image
                        ),
                    )
                except NotFoundError:
                    pass
                else:
                    output_dir = root_dir + '/' + course_dir + '/static/images/'
                    if not os.path.isdir(output_dir):
                        os.makedirs(output_dir)
                    with OSFS(output_dir).open('course_image.jpg', 'wb') as course_image_file:
                        course_image_file.write(course_image.data)

        # export the static tabs
        export_extra_content(export_fs, modulestore, course_key, xml_centric_course_key, 'static_tab', 'tabs', '.html')

        # export the custom tags
        export_extra_content(export_fs, modulestore, course_key, xml_centric_course_key, 'custom_tag_template', 'custom_tags')

        # export the course updates
        export_extra_content(export_fs, modulestore, course_key, xml_centric_course_key, 'course_info', 'info', '.html')

        # export the 'about' data (e.g. overview, etc.)
        export_extra_content(export_fs, modulestore, course_key, xml_centric_course_key, 'about', 'about', '.html')

        # export the grading policy
        course_run_policy_dir = policies_dir.makeopendir(course.location.name)
        with course_run_policy_dir.open('grading_policy.json', 'w') as grading_policy:
            grading_policy.write(dumps(course.grading_policy, cls=EdxJSONEncoder, sort_keys=True, indent=4))

        # export all of the course metadata in policy.json
        with course_run_policy_dir.open('policy.json', 'w') as course_policy:
            policy = {'course/' + course.location.name: own_metadata(course)}
            course_policy.write(dumps(policy, cls=EdxJSONEncoder, sort_keys=True, indent=4))

        #### DRAFTS ####
        # xml backed courses don't support drafts!
        if course.runtime.modulestore.get_modulestore_type() != ModuleStoreEnum.Type.xml:
            # NOTE: we need to explicitly implement the logic for setting the vertical's parent
            # and index here since the XML modulestore cannot load draft modules
            with modulestore.branch_setting(ModuleStoreEnum.Branch.draft_preferred, course_key):
                draft_modules = modulestore.get_items(
                    course_key,
                    qualifiers={'category': {'$nin': DIRECT_ONLY_CATEGORIES}},
                    revision=ModuleStoreEnum.RevisionOption.draft_only
                )

                if draft_modules:
                    draft_course_dir = export_fs.makeopendir(DRAFT_DIR)

                    # accumulate tuples of draft_modules and their parents in
                    # this list:
                    draft_node_list = []

                    for draft_module in draft_modules:
                        parent_loc = modulestore.get_parent_location(
                            draft_module.location,
                            revision=ModuleStoreEnum.RevisionOption.draft_preferred
                        )
                        # Don't try to export orphaned items.
                        if parent_loc is not None:
                            logging.debug('parent_loc = {0}'.format(parent_loc))
                            draft_node = draft_node_constructor(
                                draft_module,
                                location=draft_module.location,
                                url=draft_module.location.to_deprecated_string(),
                                parent_location=parent_loc,
                                parent_url=parent_loc.to_deprecated_string(),
                            )

                            draft_node_list.append(draft_node)

                    for draft_node in get_draft_subtree_roots(draft_node_list):
                        # only export the roots of the draft subtrees
                        # since export_from_xml (called by `add_xml_to_node`)
                        # exports a whole tree

                        draft_node.module.xml_attributes['parent_url'] = draft_node.parent_url
                        parent = modulestore.get_item(draft_node.parent_location)
                        index = parent.children.index(draft_node.module.location)
                        draft_node.module.xml_attributes['index_in_children_list'] = str(index)

                        draft_node.module.runtime.export_fs = draft_course_dir
                        adapt_references(draft_node.module, xml_centric_course_key, draft_course_dir)
                        node = lxml.etree.Element('unknown')

                        draft_node.module.add_xml_to_node(node)


def adapt_references(subtree, destination_course_key, export_fs):
    """
    Map every reference in the subtree into destination_course_key and set it back into the xblock fields
    """
    subtree.runtime.export_fs = export_fs  # ensure everything knows where it's going!
    for field_name, field in subtree.fields.iteritems():
        if field.is_set_on(subtree):
            if isinstance(field, Reference):
                value = field.read_from(subtree)
                if value is not None:
                    field.write_to(subtree, field.read_from(subtree).map_into_course(destination_course_key))
            elif field_name == 'children':
                # don't change the children field but do recurse over the children
                [adapt_references(child, destination_course_key, export_fs) for child in subtree.get_children()]
            elif isinstance(field, ReferenceList):
                field.write_to(
                    subtree,
                    [ele.map_into_course(destination_course_key) for ele in field.read_from(subtree)]
                )
            elif isinstance(field, ReferenceValueDict):
                field.write_to(
                    subtree, {
                        key: ele.map_into_course(destination_course_key) for key, ele in field.read_from(subtree).iteritems()
                    }
                )



def _export_field_content(xblock_item, item_dir):
    """
    Export all fields related to 'xblock_item' other than 'metadata' and 'data' to json file in provided directory
    """
    module_data = xblock_item.get_explicitly_set_fields_by_scope(Scope.content)
    if isinstance(module_data, dict):
        for field_name in module_data:
            if field_name not in DEFAULT_CONTENT_FIELDS:
                # filename format: {dirname}.{field_name}.json
                with item_dir.open('{0}.{1}.{2}'.format(xblock_item.location.name, field_name, 'json'),
                                   'w') as field_content_file:
                    field_content_file.write(dumps(module_data.get(field_name, {}), cls=EdxJSONEncoder, sort_keys=True, indent=4))


def export_extra_content(export_fs, modulestore, source_course_key, dest_course_key, category_type, dirname, file_suffix=''):
    items = modulestore.get_items(source_course_key, qualifiers={'category': category_type})

    if len(items) > 0:
        item_dir = export_fs.makeopendir(dirname)
        for item in items:
            adapt_references(item, dest_course_key, export_fs)
            with item_dir.open(item.location.name + file_suffix, 'w') as item_file:
                item_file.write(item.data.encode('utf8'))

                # export content fields other then metadata and data in json format in current directory
                _export_field_content(item, item_dir)


def convert_between_versions(source_dir, target_dir):
    """
    Converts a version 0 export format to version 1, and vice versa.

    @param source_dir: the directory structure with the course export that should be converted.
       The contents of source_dir will not be altered.
    @param target_dir: the directory where the converted export should be written.
    @return: the version number of the converted export.
    """
    def convert_to_version_1():
        """ Convert a version 0 archive to version 0 """
        os.mkdir(copy_root)
        with open(copy_root / EXPORT_VERSION_FILE, 'w') as f:
            f.write('{{"{export_key}": 1}}\n'.format(export_key=EXPORT_VERSION_KEY))

        # If a drafts folder exists, copy it over.
        copy_drafts()

        # Now copy everything into the published directory
        published_dir = copy_root / PUBLISHED_DIR
        shutil.copytree(path(source_dir) / course_name, published_dir)
        # And delete the nested drafts directory, if it exists.
        nested_drafts_dir = published_dir / DRAFT_DIR
        if nested_drafts_dir.isdir():
            shutil.rmtree(nested_drafts_dir)

    def convert_to_version_0():
        """ Convert a version 1 archive to version 0 """
        # Copy everything in "published" up to the top level.
        published_dir = path(source_dir) / course_name / PUBLISHED_DIR
        if not published_dir.isdir():
            raise ValueError("a version 1 archive must contain a published branch")

        shutil.copytree(published_dir, copy_root)

        # If there is a DRAFT branch, copy it. All other branches are ignored.
        copy_drafts()

    def copy_drafts():
        """
        Copy drafts directory from the old archive structure to the new.
        """
        draft_dir = path(source_dir) / course_name / DRAFT_DIR
        if draft_dir.isdir():
            shutil.copytree(draft_dir, copy_root / DRAFT_DIR)

    root = os.listdir(source_dir)
    if len(root) != 1 or (path(source_dir) / root[0]).isfile():
        raise ValueError("source archive does not have single course directory at top level")

    course_name = root[0]

    # For this version of the script, we simply convert back and forth between version 0 and 1.
    original_version = get_version(path(source_dir) / course_name)
    if original_version not in [0, 1]:
        raise ValueError("unknown version: " + str(original_version))
    desired_version = 1 if original_version is 0 else 0

    copy_root = path(target_dir) / course_name

    if desired_version == 1:
        convert_to_version_1()
    else:
        convert_to_version_0()

    return desired_version


def get_version(course_path):
    """
    Return the export format version number for the given
    archive directory structure (represented as a path instance).

    If the archived file does not correspond to a known export
    format, None will be returned.
    """
    format_file = course_path / EXPORT_VERSION_FILE
    if not format_file.isfile():
        return 0
    with open(format_file, "r") as f:
        data = json.load(f)
        if EXPORT_VERSION_KEY in data:
            return data[EXPORT_VERSION_KEY]

    return None
