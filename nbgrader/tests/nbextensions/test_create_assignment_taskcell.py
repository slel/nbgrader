import os
import pytest

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException, NoAlertPresentException
from selenium.webdriver.common.action_chains import ActionChains
from textwrap import dedent

from ...nbgraderformat import read
from .conftest import _make_nbserver, _make_browser, _close_nbserver, _close_browser
from nbformat import current_nbformat
import shutil

@pytest.fixture(scope="module")
def nbserver(request, port, tempdir, jupyter_config_dir, jupyter_data_dir, exchange, cache):
    server = _make_nbserver("", port, tempdir, jupyter_config_dir, jupyter_data_dir, exchange, cache)

    def fin():
        _close_nbserver(server)
    request.addfinalizer(fin)

    return server


@pytest.fixture(scope="module")
def browser(request, tempdir, nbserver):
    browser = _make_browser(tempdir)

    def fin():
        _close_browser(browser)
    request.addfinalizer(fin)

    return browser


def _wait(browser):
    return WebDriverWait(browser, 30)


def _load_notebook(browser, port, retries=5, name="blank"):
    # go to the correct page
    url = "http://localhost:{}/notebooks/{}.ipynb".format(port, name)
    browser.get(url)

    alert = ''
    for _ in range(5):
        if alert is None:
            break

        try:
            alert = browser.switch_to_alert()
        except NoAlertPresentException:
            alert = None
        else:
            print("Warning: dismissing unexpected alert ({})".format(alert.text))
            alert.accept()

    def page_loaded(browser):
        return browser.execute_script(
            """
            return (typeof Jupyter !== "undefined" &&
                    Jupyter.page !== undefined &&
                    Jupyter.notebook !== undefined &&
                    $("#notebook_name").text() === "{}");
            """.format(name))

    # wait for the page to load
    try:
        _wait(browser).until(page_loaded)
    except TimeoutException:
        if retries > 0:
            print("Retrying page load...")
            # page timeout, but sometimes this happens, so try refreshing?
            _load_notebook(browser, port, retries=retries - 1, name=name)
        else:
            print("Failed to load the page too many times")
            raise



def _activate_toolbar(browser, name="Create%20Assignment"):
    def celltoolbar_exists(browser):
        return browser.execute_script(
            """
            return typeof $ !== "undefined" && $ !== undefined &&
                $("#view_menu #menu-cell-toolbar").find("[data-name=\'{}\']").length == 1;
            """.format(name))

    # wait for the view menu to appear
    _wait(browser).until(celltoolbar_exists)

    # activate the Create Assignment toolbar
    browser.execute_script(
        "$('#view_menu #menu-cell-toolbar').find('[data-name=\"{}\"]').find('a').click();".format(name)
    )

    # make sure the toolbar appeared
    if name == "Create%20Assignment":
        _wait(browser).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".celltoolbar select")))
    elif name == "Edit%20Metadata":
        _wait(browser).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".celltoolbar button")))


def _select_none(browser, index=0):
    select = Select(browser.find_elements_by_css_selector('.celltoolbar select')[index])
    select.select_by_value('')


def _select_manual(browser, index=0):
    select = Select(browser.find_elements_by_css_selector('.celltoolbar select')[index])
    select.select_by_value('manual')

def _select_task(browser, index=0):
    select = Select(browser.find_elements_by_css_selector('.celltoolbar select')[index])
    select.select_by_value('task')


def _select_solution(browser, index=0):
    select = Select(browser.find_elements_by_css_selector('.celltoolbar select')[index])
    select.select_by_value('solution')


def _select_tests(browser, index=0):
    select = Select(browser.find_elements_by_css_selector('.celltoolbar select')[index])
    select.select_by_value('tests')


def _select_locked(browser, index=0):
    select = Select(browser.find_elements_by_css_selector('.celltoolbar select')[index])
    select.select_by_value('readonly')


def _set_points(browser, points=2, index=0):
    # This is a bit of a hack to use .val() and .change() rather than
    # using Selenium's sendkeys, but I can't get it to reliably work. It works
    # on Windows (both headless and non-) and headless on mac but not when
    # running with the visible browser on mac. I wasn't able to find any issues
    # regarding this and think it has something to do with the notebook
    # capturing keypresses, but wasn't able to make any further progress
    # debugging the problem.
    browser.execute_script(
        """
        $($(".nbgrader-points-input")[{}]).val("{}").change().blur();
        """.format(index, points)
    )
    browser.find_elements_by_css_selector(".nbgrader-cell")[index].click()


def _set_id(browser, cell_id="foo", index=0):
    # This is a hack, see the comment in _set_points above.
    browser.execute_script(
        """
        $($(".nbgrader-id-input")[{}]).val("{}").change().blur();
        """.format(index, cell_id)
    )
    browser.find_elements_by_css_selector(".nbgrader-cell")[index].click()


def _get_metadata(browser):
    return browser.execute_script(
        """
        var cell = Jupyter.notebook.get_cell(0);
        return cell.metadata.nbgrader;
        """
    )


def _get_total_points(browser):
    element = browser.find_element_by_id("nbgrader-total-points")
    return float(element.get_attribute("value"))


def _save(browser):
    browser.execute_script(dedent(
        """
        Jupyter._notebook_saved = false;
        Jupyter.notebook.save_notebook().then(function () {
            Jupyter._notebook_saved = true;
        });
        """
    ))

    def is_saved(browser):
        return browser.execute_script(dedent(
            """
            if (Jupyter._notebook_saved === true) {
                Jupyter._notebook_saved = false;
                return true;
            } else {
                return false;
            }
            """
        ))

    return is_saved


def _save_and_validate(browser):
    _wait(browser).until(_save(browser))
    read("blank.ipynb", current_nbformat)


def _wait_for_modal(browser):
    _wait(browser).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".modal-dialog")))


def _dismiss_modal(browser):
    button = browser.find_element_by_css_selector(".modal-footer .btn-primary")
    button.click()

    def modal_gone(browser):
        try:
            browser.find_element_by_css_selector(".modal-dialog")
        except NoSuchElementException:
            return True
        return False
    _wait(browser).until(modal_gone)


def _save_screenshot(browser):
    browser.save_screenshot(os.path.join(os.path.dirname(__file__), "selenium.screenshot.png"))



def test_task_cell(browser, port):
    _load_notebook(browser, port, name='task')
    _activate_toolbar(browser)

    # does the nbgrader metadata exist?
    assert _get_metadata(browser) is None

    # make it manually graded
    _select_task(browser)
    assert _get_metadata(browser)['task']
    assert not _get_metadata(browser)['solution']
    assert not _get_metadata(browser)['grade']
    assert _get_metadata(browser)['locked']

    # wait for the points and id fields to appear
    _wait(browser).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".nbgrader-points-input")))
    _wait(browser).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".nbgrader-id-input")))

    # set the points
    _set_points(browser)
    assert 2 == _get_metadata(browser)['points']

    # set the id
    assert _get_metadata(browser)['grade_id'].startswith("cell-")
    _set_id(browser)
    assert "foo" == _get_metadata(browser)['grade_id']

    # make sure the metadata is valid
    _save_and_validate(browser)

    # make it nothing
    _select_none(browser)
    assert not _get_metadata(browser)
    _save_and_validate(browser)




@pytest.mark.nbextensions
def test_tests_to_solution_cell(browser, port):
    _load_notebook(browser, port)
    _activate_toolbar(browser)

    # does the nbgrader metadata exist?
    assert _get_metadata(browser) is None

    # make it autograder tests
    _select_tests(browser)
    assert not _get_metadata(browser)['solution']
    assert _get_metadata(browser)['grade']
    assert _get_metadata(browser)['locked']

    # wait for the points and id fields to appear
    _wait(browser).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".nbgrader-points")))
    _wait(browser).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".nbgrader-id")))
    WebDriverWait(browser, 30).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".lock-button")))

    # set the points
    _set_points(browser)
    assert 2 == _get_metadata(browser)['points']

    # set the id
    assert _get_metadata(browser)['grade_id'].startswith("cell-")
    _set_id(browser)
    assert "foo" == _get_metadata(browser)['grade_id']

    # make sure the metadata is valid
    _save_and_validate(browser)

    # make it a solution cell and make sure the points are gone
    _select_solution(browser)
    assert _get_metadata(browser)['solution']
    assert not _get_metadata(browser)['grade']
    assert not _get_metadata(browser)['locked']
    assert 'points' not in _get_metadata(browser)
    _save_and_validate(browser)

    # make it nothing
    _select_none(browser)
    assert not _get_metadata(browser)
    _save_and_validate(browser)


@pytest.mark.nbextensions
def test_total_points(browser, port):
    _load_notebook(browser, port,'task')
    _activate_toolbar(browser)

    # make sure the total points is zero
    assert _get_total_points(browser) == 0

    # make it autograder tests and set the points to two
    _select_task(browser)
    _set_points(browser)
    _set_id(browser)
    assert _get_total_points(browser) == 2

    # make it manually graded
    _select_manual(browser)
    assert _get_total_points(browser) == 2

    # make it a solution make sure the total points is zero
    _select_solution(browser)
    assert _get_total_points(browser) == 0

    # make it task 
    _select_task(browser)
    assert _get_total_points(browser) == 0
    _set_points(browser)
    assert _get_total_points(browser) == 2

    # create a new cell
    element = browser.find_element_by_tag_name("body")
    element.send_keys(Keys.ESCAPE)
    element.send_keys("b")

    # make sure the toolbar appeared
    def find_toolbar(browser):
        try:
            browser.find_elements_by_css_selector(".celltoolbar select")[1]
        except IndexError:
            return False
        return True
    _wait(browser).until(find_toolbar)

    # make it a test cell
    _select_tests(browser, index=1)
    _set_points(browser, points=1, index=1)
    _set_id(browser, cell_id="bar", index=1)
    assert _get_total_points(browser) == 3

    # delete the new cell
    element = browser.find_elements_by_css_selector(".cell")[0]
    element.click()
    element.send_keys(Keys.ESCAPE)
    element.send_keys("d")
    element.send_keys("d")
    assert _get_total_points(browser) == 1

    # delete the first cell
    element = browser.find_elements_by_css_selector(".cell")[0]
    element.send_keys("d")
    element.send_keys("d")
    assert _get_total_points(browser) == 0

@pytest.mark.nbextensions
def test_task_cell_ids(browser, port):
    _load_notebook(browser, port, name='task')
    _activate_toolbar(browser)

    # turn it into a cell with an id
    _select_task(browser)
    _set_id(browser, cell_id="")

    # save and check for an error (blank id)
    _save(browser)
    _wait_for_modal(browser)
    _dismiss_modal(browser)

    # set the label
    _set_id(browser)

    # create a new cell
    element = browser.find_element_by_tag_name("body")
    element.send_keys(Keys.ESCAPE)
    element.send_keys("b")

    # make sure the toolbar appeared
    def find_toolbar(browser):
        try:
            browser.find_elements_by_css_selector(".celltoolbar select")[1]
        except IndexError:
            return False
        return True
    _wait(browser).until(find_toolbar)

    # make it a test cell and set the label
    _select_task(browser, index=1)
    _set_id(browser, index=1)

    # save and check for an error (duplicate id)
    _save(browser)
    _wait_for_modal(browser)
    _dismiss_modal(browser)


@pytest.mark.nbextensions
def test_negative_points(browser, port):
    _load_notebook(browser, port,'task')
    _activate_toolbar(browser)

    # make sure the total points is zero
    assert _get_total_points(browser) == 0

    # make it autograder tests and set the points to two
    _select_task(browser)
    _set_points(browser, points=2)
    _set_id(browser)
    assert _get_total_points(browser) == 2
    assert 2 == _get_metadata(browser)['points']

    # set the points to negative one
    _set_points(browser, points=-1)
    assert _get_total_points(browser) == 0
    assert 0 == _get_metadata(browser)['points']



################################################################################
####### DO NOT ADD TESTS BELOW THIS LINE #######################################
################################################################################

@pytest.mark.nbextensions
def test_final(browser, port):
    """This is a final test to be run so that the browser doesn't hang, see
    https://github.com/mozilla/geckodriver/issues/1151
    """
    _load_notebook(browser, port)
