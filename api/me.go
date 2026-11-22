package main

import (
	"errors"
	"net/http"
)

var (
	// errNoUser means the request does not identify a current user (401).
	errNoUser = errors.New("no current user")
	// errBadMode means AUTH_MODE is not "dev" or "aws" (500).
	errBadMode = errors.New("AUTH_MODE must be dev or aws")
)

// currentEmail returns the current user's email for the given AUTH_MODE.
func currentEmail(authMode string, r *http.Request) (string, error) {
	switch authMode {
	case "dev":
		return "dev@localhost", nil
	case "aws":
		return "", errNoUser
	default:
		return "", errBadMode
	}
}
