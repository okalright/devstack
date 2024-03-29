// Generated by CoffeeScript 1.6.1
(function() {

  this.XBlock = {
    Runtime: {},
    /*
    Initialize the javascript for a single xblock element, and for all of it's
    xblock children that match requestToken. If requestToken is omitted, use the
    data-request-token attribute from element, or use the request-tokens specified on
    the children themselves.
    */

    initializeBlock: function(element, requestToken) {
      var $element, block, children, data, elementTag, initFn, initFnName, initargs, runtime, version, _ref, _ref1;
      $element = $(element);
      requestToken = requestToken || $element.data('request-token');
      children = this.initializeBlocks($element, requestToken);
      runtime = $element.data("runtime-class");
      version = $element.data("runtime-version");
      initFnName = $element.data("init");
      $element.prop('xblock_children', children);
      if ((runtime != null) && (version != null) && (initFnName != null)) {
        runtime = new window[runtime]["v" + version];
        initFn = window[initFnName];
        if (initFn.length > 2) {
          initargs = $(".xblock_json_init_args", element);
          if (initargs.length === 0) {
            console.log("Warning: XBlock expects data parameters");
          }
          data = JSON.parse(initargs.text());
          block = (_ref = initFn(runtime, element, data)) != null ? _ref : {};
        } else {
          block = (_ref1 = initFn(runtime, element)) != null ? _ref1 : {};
        }
        block.runtime = runtime;
      } else {
        elementTag = $('<div>').append($element.clone()).html();
        console.log("Block " + elementTag + " is missing data-runtime, data-runtime-version or data-init, and can't be initialized");
        block = {};
      }
      block.element = element;
      block.name = $element.data("name");
      block.type = $element.data("block-type");
      $element.trigger("xblock-initialized");
      $element.data("initialized", true);
      $element.addClass("xblock-initialized");
      return block;
    },
    /*
    Initialize all XBlocks inside element that were rendered with requestToken.
    If requestToken is omitted, and element has a 'data-request-token' attribute, use that.
    If neither is available, then use the request tokens of the immediateDescendent xblocks.
    */

    initializeBlocks: function(element, requestToken) {
      var selector,
        _this = this;
      requestToken = requestToken || $(element).data('request-token');
      if (requestToken) {
        selector = ".xblock[data-request-token='" + requestToken + "']";
      } else {
        selector = ".xblock";
      }
      return $(element).immediateDescendents(selector).map(function(idx, elem) {
        return _this.initializeBlock(elem, requestToken);
      }).toArray();
    }
  };

}).call(this);
