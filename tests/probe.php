<?php
// What this PHP lets a script do, as one JSON line; tests/probe.sh compares it
// with what the protections in patches/series and the image's allowances say.
$object = 'O:8:"stdClass":0:{}';
echo json_encode([
	'functions' => array_values(array_filter(
		['dl', 'exec', 'passthru', 'pcntl_exec', 'popen', 'proc_open', 'shell_exec', 'system'],
		'function_exists'
	)),
	'unserialize' => get_class(unserialize($object)),
	'unserialize_all' => get_class(unserialize($object, ['allowed_classes' => true])),
	'unserialize_named' => get_class(unserialize($object, ['allowed_classes' => ['stdClass']])),
	'phar_wrapper' => in_array('phar', stream_get_wrappers(), true),
	'allow_url_include' => (bool) ini_get('allow_url_include'),
	'opcache_file_cache' => (string) ini_get('opcache.file_cache'),
	'memory_limit' => ini_get('memory_limit'),
]), "\n";
