"""
Notebook Tag
------------
This is a liquid-style tag to include a static html rendering of an IPython
notebook in a blog post.

Syntax
------
{% notebook filename.ipynb [ cells[start:end] language[language] ]%}

The file should be specified relative to the ``notebooks`` subdirectory of the
content directory.  Optionally, this subdirectory can be specified in the
config file:

    NOTEBOOK_DIR = 'notebooks'

The cells[start:end] statement is optional, and can be used to specify which
block of cells from the notebook to include.

The language statement is obvious and can be used to specify whether ipython2
or ipython3 syntax highlighting should be used.

Requirements
------------
- The plugin requires IPython version 1.0 or above.  It no longer supports the
  standalone nbconvert package, which has been deprecated.

Details
-------
Because the notebook relies on some rather extensive custom CSS, the use of
this plugin requires additional CSS to be inserted into the blog theme.
After typing "make html" when using the notebook tag, a file called
``_nb_header.html`` will be produced in the main directory.  The content
of the file should be included in the header of the theme.  An easy way
to accomplish this is to add the following lines within the header template
of the theme you use:

    {% if EXTRA_HEADER %}
      {{ EXTRA_HEADER }}
    {% endif %}

and in your ``pelicanconf.py`` file, include the line:

    EXTRA_HEADER = open('_nb_header.html').read().decode('utf-8')

this will insert the appropriate CSS.  All efforts have been made to ensure
that this CSS will not override formats within the blog theme, but there may
still be some conflicts.
"""
import warnings
import re
import os
from functools import partial
from io import open

from .mdx_liquid_tags import LiquidTags

from pelican import settings

import IPython
IPYTHON_VERSION = IPython.version_info[0]

try:
    import nbformat
except:
    pass

try:
    import IPython.nbformat
except:
    pass


if not IPYTHON_VERSION >= 1:
    raise ValueError("IPython version 1.0+ required for notebook tag")

if IPYTHON_VERSION > 1:
    warnings.warn("Pelican plugin is not designed to work with IPython "
                  "versions greater than 1.x. CSS styles have changed in "
                  "later releases.")

try:
    from nbconvert.filters.highlight import _pygments_highlight
except ImportError:
    try:
        from IPython.nbconvert.filters.highlight import _pygments_highlight
    except ImportError:
        # IPython < 2.0
        from IPython.nbconvert.filters.highlight import _pygment_highlight as _pygments_highlight

from pygments.formatters import HtmlFormatter

try:
    from nbconvert.exporters import HTMLExporter
except ImportError:
        from IPython.nbconvert.exporters import HTMLExporter

try:
    from traitlets.config import Config
except ImportError:
    from IPython.config import Config

try:
    from nbconvert.preprocessors import Preprocessor, ExtractOutputPreprocessor
except ImportError:
    try:
        from IPython.nbconvert.preprocessors import (Preprocessor,
                                                     ExtractOutputPreprocessor)
    except ImportError:
        # IPython < 2.0
        from IPython.nbconvert.transformers import Transformer as Preprocessor
        from IPython.nbconvert.transformers import ExtractOutputTransformer

try:
    from traitlets import Integer
except ImportError:
    from IPython.utils.traitlets import Integer

from copy import deepcopy

#----------------------------------------------------------------------
# Some code that will be added to the header:
#  Some of the following javascript/css include is adapted from
#  IPython/nbconvert/templates/fullhtml.tpl, while some are custom tags
#  specifically designed to make the results look good within the
#  pelican-octopress theme.
JS_INCLUDE = r"""
<style type="text/css">
/* Overrides of notebook CSS for static HTML export */
div.entry-content {
  overflow: visible;
  padding: 8px;
}
.input_area {
  padding: 0.2em;
}

a.heading-anchor {
 white-space: normal;
}

.rendered_html
code {
 font-size: .8em;
}

pre.ipynb {
  color: black;
  background: #f7f7f7;
  border: none;
  box-shadow: none;
  margin-bottom: 0;
  padding: 0;
  margin: 0px;
  font-size: 13px;
}

/* remove the prompt div from text cells */
div.text_cell .prompt {
    display: none;
}

/* remove horizontal padding from text cells, */
/* so it aligns with outer body text */
div.text_cell_render {
    padding: 0.5em 0em;
}

img.anim_icon{padding:0; border:0; vertical-align:middle; -webkit-box-shadow:none; -box-shadow:none}

div.collapseheader {
    width=100%;
    background-color:#d3d3d3;
    padding: 2px;
    cursor: pointer;
    font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;
}
</style>

<script src="https://cdn.mathjax.org/mathjax/latest/MathJax.js?config=TeX-AMS_HTML" type="text/javascript"></script>
<script type="text/javascript">
init_mathjax = function() {
    if (window.MathJax) {
        // MathJax loaded
        MathJax.Hub.Config({
            tex2jax: {
                inlineMath: [ ['$','$'], ["\\(","\\)"] ],
                displayMath: [ ['$$','$$'], ["\\[","\\]"] ]
            },
            displayAlign: 'left', // Change this to 'center' to center equations.
            "HTML-CSS": {
                styles: {'.MathJax_Display': {"margin": 0}}
            }
        });
        MathJax.Hub.Queue(["Typeset",MathJax.Hub]);
    }
}
init_mathjax();
</script>
<script src="https://ajax.googleapis.com/ajax/libs/jquery/1.10.2/jquery.min.js"></script>

<script type="text/javascript">
jQuery(document).ready(function($) {
    $("div.collapseheader").click(function () {
    $header = $(this).children("span").first();
    $codearea = $(this).children(".input_area");
    console.log($(this).children());
    $codearea.slideToggle(500, function () {
        $header.text(function () {
            return $codearea.is(":visible") ? "Collapse Code" : "Expand Code";
        });
    });
});
});
</script>

"""

CSS_WRAPPER = """
<style type="text/css">
{0}
</style>
"""


#----------------------------------------------------------------------
# Create a custom preprocessor
class SliceIndex(Integer):
    """An integer trait that accepts None"""
    default_value = None

    def validate(self, obj, value):
        if value is None:
            return value
        else:
            return super(SliceIndex, self).validate(obj, value)


class SubCell(Preprocessor):
    """A transformer to select a slice of the cells of a notebook"""
    start = SliceIndex(0, config=True,
                       help="first cell of notebook to be converted")
    end = SliceIndex(None, config=True,
                     help="last cell of notebook to be converted")

    def preprocess(self, nb, resources):
        nbc = deepcopy(nb)
        if IPYTHON_VERSION < 3:
            for worksheet in nbc.worksheets:
                cells = worksheet.cells[:]
                worksheet.cells = cells[self.start:self.end]
        else:
            nbc.cells = nbc.cells[self.start:self.end]

        return nbc, resources

    call = preprocess # IPython < 2.0



#----------------------------------------------------------------------
# Custom highlighter:
#  instead of using class='highlight', use class='highlight-ipynb'
def custom_highlighter(source, language='ipython', metadata=None):
    formatter = HtmlFormatter(cssclass='highlight-ipynb')
    if not language:
        language = 'ipython'
    output = _pygments_highlight(source, formatter, language)
    return output.replace('<pre>', '<pre class="ipynb">')


#----------------------------------------------------------------------
# Below is the pelican plugin code.
#
SYNTAX = "{% notebook /path/to/notebook.ipynb [ cells[start:end] ] [ language[language] ] %}"
FORMAT = re.compile(r"""^(\s+)?(?P<src>\S+)(\s+)?((cells\[)(?P<start>-?[0-9]*):(?P<end>-?[0-9]*)(\]))?(\s+)?((language\[)(?P<language>-?[a-z0-9\+\-]*)(\]))?(\s+)?$""")


@LiquidTags.register('notebook')
def notebook(preprocessor, tag, markup):
    match = FORMAT.search(markup)
    if match:
        argdict = match.groupdict()
        src = argdict['src']
        start = argdict['start']
        end = argdict['end']
        language = argdict['language']
    else:
        raise ValueError("Error processing input, "
                         "expected syntax: {0}".format(SYNTAX))

    if start:
        start = int(start)
    else:
        start = 0

    if end:
        end = int(end)
    else:
        end = None

    language_applied_highlighter = partial(custom_highlighter, language=language)

    config_dict = {'CSSHTMLHeaderTransformer':
                       {'enabled':True, 'highlight_class':'.highlight-ipynb'},
                   'SubCell':
                       {'enabled':True, 'start':start, 'end':end},
                }

    nb_dir = preprocessor.configs.getConfig('NOTEBOOK_DIR')
    nb_path = os.path.join('content', nb_dir, src)

    if not os.path.exists(nb_path):
        raise ValueError("File {0} could not be found".format(nb_path))

    notebook_output =  preprocessor.configs.getConfig('NOTEBOOK_OUTPUT')
    if notebook_output is not False:
        output_prefix = os.path.join('content', notebook_output)
        # Note: This should be relative to the *target* fpath, but we don't
        # have that context within this extension. :(
        rel_output_prefix = os.path.relpath(output_prefix,
                                            os.path.dirname(nb_path))
        tmpl = (os.path.join(rel_output_prefix, os.path.splitext(src)[0]) +
                '_{unique_key}_{cell_index}_{index}{extension}')

        config_dict.update({'ExtractOutputPreprocessor':
                                {'enabled': True,
                                 'output_filename_template': tmpl}})

    # Create the custom notebook converter
    c = Config(config_dict)

    template_file = 'basic'
    if IPYTHON_VERSION >= 3:
        if os.path.exists('pelicanhtml_3.tpl'):
            template_file = 'pelicanhtml_3'
    elif IPYTHON_VERSION == 2:
        if os.path.exists('pelicanhtml_2.tpl'):
            template_file = 'pelicanhtml_2'
    else:
        if os.path.exists('pelicanhtml_1.tpl'):
            template_file = 'pelicanhtml_1'

    if IPYTHON_VERSION >= 2:
        kwargs = dict(preprocessors=[SubCell,
                                     ExtractOutputPreprocessor])
    else:
        kwargs = dict(transformers=[SubCell,
                                    ExtractOutputTransformer])

    exporter = HTMLExporter(config=c,
                            template_file=template_file,
                            filters={'highlight2html': language_applied_highlighter},
                            **kwargs)

    # read and parse the notebook
    with open(nb_path, encoding='utf-8') as f:
        nb_text = f.read()
        if IPYTHON_VERSION < 3:
            nb_json = IPython.nbformat.current.reads_json(nb_text)
        else:
            try:
                nb_json = nbformat.reads(nb_text, as_version=4)
            except:
                nb_json = IPython.nbformat.reads(nb_text, as_version=4)

    (body, resources) = exporter.from_notebook_node(nb_json)
    for name, data in resources.get('outputs', {}).items():
        # We hardcode the output directory here... :(
        full = os.path.join('output', name.replace('../', ''))
        new_name = os.path.normpath(full)
        if not os.path.isdir(os.path.dirname(new_name)):
            os.makedirs(os.path.dirname(new_name))
        # Note: It seems we need to run the pelican build script twice,
        # for the new images to be copied.
        with open(new_name, 'wb') as f:
            f.write(data)

    # if we haven't already saved the header, save it here.
    if not notebook.header_saved:
        print ("\n ** Writing styles to _nb_header.html: "
               "this should be included in the theme. **\n")

        header = '\n'.join(CSS_WRAPPER.format(css_line)
                           for css_line in resources['inlining']['css'])
        header += JS_INCLUDE

        with open('_nb_header.html', 'w') as f:
            f.write(header)
        notebook.header_saved = True

    # this will stash special characters so that they won't be transformed
    # by subsequent processes.
    body = preprocessor.configs.htmlStash.store(body, safe=True)
    return body

notebook.header_saved = False


#----------------------------------------------------------------------
# This import allows notebook to be a Pelican plugin
from liquid_tags import register
